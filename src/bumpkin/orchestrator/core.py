from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, cast

from bumpkin.analysis import explanation_facts as explanation_dsl
from bumpkin.analysis.case_file import build_case_file, render_case_file_text
from bumpkin.analysis.diffing import DiffResult
from bumpkin.analysis.evidence import build_evidence_items, summarize_evidence_items
from bumpkin.analysis.findings import (
    Finding,
    aggregate_findings,
    build_filesystem_workspace_loader,
    detect_semver_findings,
)
from bumpkin.analysis.impact import summarize_impact
from bumpkin.config import BumpkinConfig
from bumpkin.contracts import build_coverage_contract
from bumpkin.orchestrator import adjudication as orchestrator_adjudication
from bumpkin.orchestrator import court as orchestrator_court
from bumpkin.orchestrator import explanation_polish
from bumpkin.orchestrator import finalize as orchestrator_finalize
from bumpkin.planner import PlannerDecision
from bumpkin.policies import engine as policy_engine
from bumpkin.policies import guards as guard_policies
from bumpkin.prompt_pack import PromptPackMetadata
from bumpkin.providers.llm import get_no_bump_recommendation, get_stub_recommendation
from bumpkin.providers.semantic import semantic_fallback_recommendation
from bumpkin.versioning.tags import detect_next_version

CHANGELOG_PATTERN = explanation_polish.CHANGELOG_PATTERN
_extract_polish_payload = explanation_polish.extract_polish_payload
_is_human_readable_explanation = explanation_polish.is_human_readable_explanation
_polish_explanation_with_model = explanation_polish.polish_explanation_with_model
_should_run_explanation_polish = explanation_polish.should_run_explanation_polish
_validate_polish_payload = explanation_polish.validate_polish_payload


def _as_object_list(value: object) -> list[object] | None:
    if not isinstance(value, list):
        return None
    return cast("list[object]", value)


def _as_dict(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return cast("dict[str, Any]", value)


ACTION_VERBS_BY_LABEL = {
    "MAJOR": ("break", "remove", "rename", "replace", "deprecate", "migrate", "change"),
    "MINOR": ("add", "introduce", "extend", "support", "expose", "enable"),
    "PATCH": ("fix", "update", "refine", "adjust", "improve", "harden"),
    "NO_BUMP": ("document", "annotate", "format", "reorganize", "maintain", "no release"),
}
NON_RUNTIME_EXTENSIONS = (".md", ".mdx", ".rst", ".txt")
NON_RUNTIME_PATH_PREFIXES = ("docs/", ".github/")
NON_RUNTIME_BASENAMES = {
    "readme.md",
    "changelog.md",
    "license",
    "license.md",
    "contributing.md",
    "security.md",
    "renovate.json",
}


def _is_explanation_dsl_enabled() -> bool:
    raw = os.getenv("BUMPKIN_EXPLANATION_DSL", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


@dataclass(frozen=True)
class CoreAnalysisResult:
    output: dict[str, Any]
    result: dict[str, Any]
    notes: list[str]
    findings: list[Finding]
    mode_used: str
    fallback_reason: str | None
    current_tag: str | None
    next_tag: str | None
    override_summary: str | None
    override_status: str
    aggregation_trace: str | None
    boundary_summary: dict[str, int]
    analysis_state: str
    classification_source: str
    failure_category: str | None
    policy_effects: list[str]
    decision_trace: dict[str, Any]
    court_advisory: dict[str, Any]
    court_fallback_reason: str | None
    court_model_used: str | None
    court_skipped_reason: str | None
    deterministic_label: str | None
    deterministic_next_tag: str | None
    model_used: str | None
    explainability_rows: list[dict[str, str]]
    proof_obligations: dict[str, Any]
    reasoning_trace: list[dict[str, Any]]
    contradictions: list[dict[str, Any]]


def _workspace_loader_for_diff_result(diff_result: DiffResult):
    repo_root = (diff_result.repo_root or "").strip()
    if not repo_root:
        return None
    return build_filesystem_workspace_loader(repo_root)


def _changelog_for_label(label: str) -> str:
    normalized = label.upper()
    mapping = {
        "MAJOR": "feat: introduce breaking api changes",
        "MINOR": "feat: add backward-compatible api changes",
        "PATCH": "fix: update internal implementation",
        "NO_BUMP": "chore: no release required",
    }
    return mapping.get(normalized, "chore: no release required")


def _case_file_evidence_lookup(case_file: dict[str, Any]) -> dict[str, dict[str, str]]:
    records = _as_object_list(case_file.get("evidence_records"))
    if records is None:
        return {}
    lookup: dict[str, dict[str, str]] = {}
    for item in records:
        record = _as_dict(item)
        if record is None:
            continue
        evidence_id = str(record.get("evidence_id", "")).strip()
        if not evidence_id:
            continue
        lookup[evidence_id] = {
            "evidence_id": evidence_id,
            "rule": str(record.get("rule", "")).strip(),
            "path": str(record.get("path", "")).strip(),
            "snippet": str(record.get("snippet", "")).strip(),
        }
    return lookup


def _derive_scope_from_path(path: str, *, rule: str) -> str:
    return explanation_dsl.derive_scope_from_path(path, rule=rule)


def _summarize_path_targets(paths: list[str], *, max_items: int = 2) -> str:
    return explanation_dsl.summarize_path_targets(paths, max_items=max_items)


def _extract_symbol_hint(snippet: str) -> str | None:
    return explanation_dsl.extract_symbol_hint(snippet)


def _derive_operation_hint(snippet: str) -> str | None:
    return explanation_dsl.derive_operation_hint(snippet)


_EXPLANATION_HINT_HELPERS = (_extract_symbol_hint, _derive_operation_hint)


def _change_hint_from_records(records: list[dict[str, str]]) -> str | None:
    return explanation_dsl.change_hint_from_records(records)


def _file_anchors_from_records(records: list[dict[str, str]]) -> list[str]:
    anchors: list[str] = []
    seen: set[str] = set()
    for record in records:
        path = str(record.get("path", "")).strip()
        if not path:
            continue
        filename = path.rsplit("/", 1)[-1]
        for anchor in (filename, path):
            lowered = anchor.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            anchors.append(anchor)
    return anchors


def _merge_anchor_records(
    records: list[dict[str, str]], fallback_paths: list[str]
) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    seen_paths: set[str] = set()

    for record in records:
        path = str(record.get("path", "")).strip()
        if path:
            seen_paths.add(path.lower())
        merged.append(record)

    fallback_index = 0
    for raw_path in fallback_paths:
        path = str(raw_path).strip()
        if not path:
            continue
        lowered = path.lower()
        if lowered in seen_paths:
            continue
        seen_paths.add(lowered)
        fallback_index += 1
        merged.append(
            {
                "evidence_id": f"path_fallback:{fallback_index}",
                "rule": "changed_file_path",
                "path": path,
                "snippet": path,
            }
        )

    if not any(str(item.get("path", "")).strip() for item in merged):
        merged.append(
            {
                "evidence_id": "path_fallback:diff-context",
                "rule": "changed_diff_context",
                "path": "diff context",
                "snippet": "diff context",
            }
        )

    return merged


def _contains_action_verb(text: str, *, advisory_label: str) -> bool:
    lowered = text.lower()
    verbs = ACTION_VERBS_BY_LABEL.get(advisory_label.upper(), ())
    return any(re.search(rf"\b{re.escape(verb)}(?:d|s|ing)?\b", lowered) for verb in verbs)


def _is_template_reasoning(text: str) -> bool:
    normalized = " ".join(str(text or "").split()).strip().lower()
    if not normalized:
        return True
    template_fragments = (
        "accepted evidence indicates",
        "strongest evidence in the case file",
        "based on case-file evidence",
    )
    return any(fragment in normalized for fragment in template_fragments)


def _passes_explicitness_gate(
    *,
    reasoning: str,
    changelog: str,
    advisory_label: str,
    records: list[dict[str, str]],
) -> tuple[bool, str | None]:
    if not _is_human_readable_explanation(reasoning) or not _is_human_readable_explanation(
        changelog
    ):
        return False, "machine_tokens_detected"
    if not CHANGELOG_PATTERN.match(changelog):
        return False, "invalid_changelog_format"
    anchors = _file_anchors_from_records(records)
    if not anchors:
        return False, "missing_file_anchors"
    combined = f"{reasoning.lower()} {changelog.lower()}"
    mentioned = sum(1 for anchor in anchors if anchor.lower() in combined)
    unique_paths = {
        str(record.get("path", "")).strip().lower()
        for record in records
        if str(record.get("path", "")).strip()
    }
    required_anchor_count = 2 if len(unique_paths) >= 2 else 1
    if mentioned < required_anchor_count:
        return False, f"insufficient_file_anchors({mentioned}/{required_anchor_count})"
    if not _contains_action_verb(combined, advisory_label=advisory_label):
        return False, "missing_action_verbs"
    if _is_template_reasoning(reasoning):
        return False, "generic_template_reasoning"
    return True, None


def _build_explicit_fallback_explanation(
    *,
    advisory_label: str,
    records: list[dict[str, str]],
) -> tuple[str, str]:
    if _is_explanation_dsl_enabled():
        facts = explanation_dsl.build_explanation_facts(
            advisory_label=advisory_label,
            records=records,
            max_target_items=2,
        )
        if facts:
            dsl_reasoning = explanation_dsl.render_reasoning_from_facts(facts)
            dsl_changelog = explanation_dsl.render_changelog_from_facts(facts)
            if (
                dsl_reasoning
                and dsl_changelog
                and explanation_dsl.passes_quality_policy(dsl_reasoning)
                and explanation_dsl.passes_quality_policy(dsl_changelog)
            ):
                return dsl_reasoning, dsl_changelog

    paths = [
        str(record.get("path", "")).strip()
        for record in records
        if str(record.get("path", "")).strip()
    ]
    target_summary = _summarize_path_targets(paths, max_items=2)
    change_hint = _change_hint_from_records(records)
    detail = f" via {change_hint}" if change_hint else ""
    primary = records[0] if records else {"path": "", "rule": ""}
    scope = _derive_scope_from_path(
        paths[0] if paths else str(primary.get("path", "")),
        rule=str(primary.get("rule", "")),
    )
    label = advisory_label.upper()
    if label == "MAJOR":
        return (
            f"Court selected MAJOR because breaking behavior changed in {target_summary}{detail}.",
            f"feat({scope})!: change breaking behavior in {target_summary}{detail}",
        )
    if label == "MINOR":
        return (
            f"Court selected MINOR because new behavior was added in {target_summary}{detail}.",
            f"feat({scope}): add behavior in {target_summary}{detail}",
        )
    if label == "NO_BUMP":
        return (
            f"Court selected NO_BUMP because non-release maintenance updates were documented in {target_summary}.",
            "chore: no release required",
        )
    return (
        f"Court selected PATCH because internal logic was updated in {target_summary}{detail}.",
        f"fix({scope}): update internal logic in {target_summary}{detail}",
    )


def _enforce_explicit_explanation(
    *,
    advisory_label: str,
    reasoning: str,
    changelog: str,
    records: list[dict[str, str]],
    fallback_paths: list[str] | None = None,
) -> tuple[str, str, bool]:
    anchor_records = _merge_anchor_records(records, fallback_paths or [])
    passed, _reason = _passes_explicitness_gate(
        reasoning=reasoning,
        changelog=changelog,
        advisory_label=advisory_label,
        records=anchor_records,
    )
    if passed:
        return reasoning, changelog, False

    fallback_reasoning, fallback_changelog = _build_explicit_fallback_explanation(
        advisory_label=advisory_label,
        records=anchor_records,
    )
    passed_fallback, fallback_reason = _passes_explicitness_gate(
        reasoning=fallback_reasoning,
        changelog=fallback_changelog,
        advisory_label=advisory_label,
        records=anchor_records,
    )
    if not passed_fallback:
        raise RuntimeError(
            "Explicit explanation gate failed after deterministic regeneration: "
            f"{fallback_reason or 'unknown'}"
        )
    return fallback_reasoning, fallback_changelog, True


def _evidence_priority(advisory_label: str, record: dict[str, str]) -> int:
    rule = str(record.get("rule", "")).lower()
    path = str(record.get("path", "")).lower()
    evidence_id = str(record.get("evidence_id", "")).lower()
    score = 0
    if path.startswith("src/"):
        score += 8
    elif path and path != "<unknown>":
        score += 4
    if path.startswith("tests/") or "/test" in path:
        score -= 4
    if evidence_id.startswith("finding:"):
        score += 4
    if evidence_id.startswith("behavior_marker:"):
        score += 3
    if evidence_id.startswith("path_marker:"):
        score += 2

    normalized_label = advisory_label.upper()
    if normalized_label == "MAJOR" and any(
        token in rule for token in ("breaking", "removed", "incompatible")
    ):
        score += 8
    if normalized_label == "MINOR" and any(
        token in rule for token in ("export", "contract", "added", "feature")
    ):
        score += 8
    if normalized_label == "PATCH":
        if "changed_file_path" in rule:
            score += 8
        if any(token in rule for token in ("internal", "fix", "behavior", "refactor")):
            score += 4
    if normalized_label == "NO_BUMP" and any(token in path for token in ("docs/", "readme", ".md")):
        score += 8
    return score


def _select_explanation_records(
    *,
    advisory_label: str,
    court_advisory: dict[str, Any],
    evidence_lookup: dict[str, dict[str, str]],
    max_items: int = 3,
) -> list[dict[str, str]]:
    accepted_ids = _as_object_list(court_advisory.get("accepted_evidence_ids"))
    if accepted_ids is not None:
        normalized_ids = [str(item).strip() for item in accepted_ids if str(item).strip()]
        accepted_records = [
            evidence_lookup[item] for item in normalized_ids if item in evidence_lookup
        ]
        if accepted_records:
            return accepted_records[:max_items]

    if not evidence_lookup:
        return []

    records = list(evidence_lookup.values())
    ranked = sorted(
        enumerate(records),
        key=lambda pair: (-_evidence_priority(advisory_label, pair[1]), pair[0]),
    )
    selected = [record for _, record in ranked[:max_items]]
    return [item for item in selected if item]


def _is_non_runtime_path(path: str) -> bool:
    normalized = str(path).strip().lower()
    if not normalized:
        return False
    if normalized.startswith(NON_RUNTIME_PATH_PREFIXES):
        return True
    if normalized.endswith(NON_RUNTIME_EXTENSIONS):
        return True
    basename = normalized.rsplit("/", 1)[-1]
    return basename in NON_RUNTIME_BASENAMES


def _extract_before_after_by_path(diff_text: str) -> dict[str, tuple[str, str, str | None]]:
    pairs: dict[str, tuple[str, str, str | None]] = {}
    current_path = ""
    first_removed: dict[str, str] = {}
    first_added: dict[str, str] = {}
    first_span: dict[str, str] = {}
    for raw in diff_text.splitlines():
        header = re.match(r"^diff --git a/(.+?) b/(.+?)$", raw.strip())
        if header:
            current_path = str(header.group(2)).strip()
            continue
        if not current_path:
            continue
        hunk = re.match(r"^@@\s*-\d+(?:,\d+)?\s+\+(\d+)(?:,(\d+))?\s*@@", raw.strip())
        if hunk and current_path not in first_span:
            start = int(hunk.group(1))
            length = int(hunk.group(2) or "1")
            end = start + max(length, 1) - 1
            first_span[current_path] = f"{start}" if end == start else f"{start}-{end}"
            continue
        if raw.startswith(("---", "+++", "@@", "index ")):
            continue
        if raw.startswith("-") and not raw.startswith("---"):
            text = raw[1:].strip()
            if text and current_path not in first_removed:
                first_removed[current_path] = text[:180]
        elif raw.startswith("+") and not raw.startswith("+++"):
            text = raw[1:].strip()
            if text and current_path not in first_added:
                first_added[current_path] = text[:180]
    for path in set(first_removed) | set(first_added):
        before = first_removed.get(path, "")
        after = first_added.get(path, "")
        span = first_span.get(path)
        if before or after:
            pairs[path] = (before, after, span)
    return pairs


def _build_patch_fallback_records(
    *,
    diff_text: str,
    analyzed_files: list[str],
    max_items: int,
) -> list[dict[str, str]]:
    before_after = _extract_before_after_by_path(diff_text)
    records: list[dict[str, str]] = []
    for path in analyzed_files:
        normalized = str(path).strip()
        if not normalized or _is_non_runtime_path(normalized):
            continue
        before, after, line_span = before_after.get(normalized, ("", "", None))
        if not before and not after:
            continue
        record = {
            "evidence_id": f"runtime_delta:{len(records) + 1}",
            "rule": "internal_runtime_delta",
            "severity": "PATCH",
            "path": normalized,
            "snippet": after or before,
            "before": before or "previous behavior",
            "after": after or "updated behavior",
            "impact_reason": "internal runtime behavior changed",
        }
        if line_span:
            record["line_span"] = line_span
        records.append(record)
        if len(records) >= max_items:
            break
    return records


def _build_no_bump_invariance_records(
    *, analyzed_files: list[str], max_items: int
) -> list[dict[str, str]]:
    normalized = [str(path).strip() for path in analyzed_files if str(path).strip()]
    if not normalized:
        return []
    if not all(_is_non_runtime_path(path) for path in normalized):
        return []
    records: list[dict[str, str]] = []
    for index, path in enumerate(normalized[:max_items]):
        records.append(
            {
                "evidence_id": f"invariance:{index + 1}",
                "rule": "runtime_contract_unchanged",
                "severity": "NO_BUMP",
                "path": path,
                "snippet": path,
                "before": "runtime contract unchanged",
                "after": "runtime contract unchanged",
                "impact_reason": "non-runtime-only changes",
            }
        )
    return records


def _build_explainability_rows(
    *,
    advisory_label: str,
    court_advisory: dict[str, Any],
    evidence_lookup: dict[str, dict[str, str]],
    analyzed_files: list[str],
    diff_text: str,
    max_items: int = 8,
) -> list[dict[str, str]]:
    records = _select_explanation_records(
        advisory_label=advisory_label,
        court_advisory=court_advisory,
        evidence_lookup=evidence_lookup,
        max_items=max_items,
    )
    semantic_selected = [
        record
        for record in records
        if not explanation_dsl.is_path_only_delta_rule(str(record.get("rule", "")))
    ]
    if semantic_selected:
        return explanation_dsl.build_delta_rows(
            advisory_label=advisory_label,
            records=semantic_selected,
            max_items=max_items,
        )

    semantic_available = [
        record
        for record in evidence_lookup.values()
        if not explanation_dsl.is_path_only_delta_rule(str(record.get("rule", "")))
    ]
    if semantic_available:
        return explanation_dsl.build_delta_rows(
            advisory_label=advisory_label,
            records=semantic_available[:max_items],
            max_items=max_items,
        )

    if advisory_label.upper() == "PATCH":
        patch_records = _build_patch_fallback_records(
            diff_text=diff_text,
            analyzed_files=analyzed_files,
            max_items=max_items,
        )
        if patch_records:
            return explanation_dsl.build_delta_rows(
                advisory_label=advisory_label,
                records=patch_records,
                max_items=max_items,
            )

    if advisory_label.upper() == "NO_BUMP":
        invariance_records = _build_no_bump_invariance_records(
            analyzed_files=analyzed_files,
            max_items=max_items,
        )
        if invariance_records:
            return explanation_dsl.build_delta_rows(
                advisory_label=advisory_label,
                records=invariance_records,
                max_items=max_items,
            )
    return []


def _row_has_semantic_transition(row: dict[str, str]) -> bool:
    before = str(row.get("before", "")).strip()
    after = str(row.get("after", "")).strip()
    if before and after:
        return True
    action = str(row.get("action", "")).strip().lower()
    return action in {"added", "removed", "renamed", "tightened", "unchanged"}


def _row_satisfies_patch_transition(row: dict[str, str]) -> bool:
    impact_scope = str(row.get("impact_scope", "")).strip().lower()
    suggested_bump = str(row.get("suggested_bump", "")).strip().upper()
    if impact_scope != "runtime_internal" or suggested_bump != "PATCH":
        return False
    return _row_has_semantic_transition(row)


def _evaluate_proof_obligations(
    *,
    status: str,
    evaluated_label: str | None,
    semantic_facts: list[dict[str, str]],
) -> dict[str, Any]:
    required: list[str] = [
        "semantic_fact_present",
        "semantic_fact_evidence_path_present",
        "semantic_fact_transition_present",
    ]
    label = str(evaluated_label or "").strip().upper()
    if label == "PATCH":
        required.append("runtime_delta_transition_present")
    if label == "NO_BUMP":
        required.append("runtime_invariance_fact_present")

    fact_present = bool(semantic_facts)
    has_paths = fact_present and all(str(item.get("path", "")).strip() for item in semantic_facts)
    has_transitions = fact_present and all(
        _row_has_semantic_transition(item) for item in semantic_facts
    )
    patch_transition = (
        any(_row_satisfies_patch_transition(item) for item in semantic_facts)
        if label == "PATCH"
        else True
    )
    no_bump_invariance = (
        any(
            str(item.get("rule", "")).strip().lower() == "runtime_contract_unchanged"
            and str(item.get("before", "")).strip() == "runtime contract unchanged"
            and str(item.get("after", "")).strip() == "runtime contract unchanged"
            for item in semantic_facts
        )
        if label == "NO_BUMP"
        else True
    )

    checks = {
        "semantic_fact_present": fact_present,
        "semantic_fact_evidence_path_present": has_paths,
        "semantic_fact_transition_present": has_transitions,
        "runtime_delta_transition_present": patch_transition,
        "runtime_invariance_fact_present": no_bump_invariance,
    }
    satisfied = [item for item in required if checks.get(item, False)]
    missing = [item for item in required if not checks.get(item, False)]

    critical_policy = {
        "semantic_fact_present",
        "semantic_fact_evidence_path_present",
        "runtime_delta_transition_present",
        "runtime_invariance_fact_present",
    }
    critical_missing = [item for item in missing if item in critical_policy]
    return {
        "version": "proof_obligations_v1",
        "evaluated_label": label or None,
        "status": status,
        "required": required,
        "satisfied": satisfied,
        "missing": missing,
        "critical_missing": critical_missing,
    }


def _critical_missing_proof_obligations(proof_obligations: dict[str, Any]) -> list[str]:
    raw_missing = _as_object_list(proof_obligations.get("critical_missing", []))
    if raw_missing is None:
        return []
    normalized: list[str] = []
    for value in raw_missing:
        if not isinstance(value, str):
            continue
        item = value.strip()
        if item:
            normalized.append(item)
    return normalized


def _semantic_severity_rank(label: str) -> int:
    ordering = {"MAJOR": 4, "MINOR": 3, "PATCH": 2, "NO_BUMP": 1}
    return ordering.get(label.upper(), 0)


def _extract_contradiction_paths(contradictions: list[dict[str, Any]]) -> set[str]:
    paths: set[str] = set()
    for item in contradictions:
        raw_paths = _as_object_list(item.get("evidence_paths", []))
        if raw_paths is None:
            continue
        for path in raw_paths:
            normalized = str(path).strip()
            if normalized:
                paths.add(normalized)
    return paths


def _prioritize_semantic_facts(
    semantic_facts: list[dict[str, str]],
    *,
    contradiction_paths: set[str],
    max_items: int = 8,
) -> list[dict[str, str]]:
    def _priority(row: dict[str, str]) -> tuple[int, int, str, str, str]:
        impact_scope = str(row.get("impact_scope", "")).strip().lower()
        suggested = str(row.get("suggested_bump", "")).strip().upper()
        path = str(row.get("path", "")).strip()
        rule = str(row.get("rule", "")).strip()
        target = str(row.get("target", "")).strip()
        if impact_scope == "public_api":
            bucket = 0
        elif path in contradiction_paths:
            bucket = 1
        elif suggested == "PATCH" and impact_scope == "runtime_internal":
            bucket = 3
        else:
            bucket = 2
        return (bucket, -_semantic_severity_rank(suggested), path, rule, target)

    ranked = sorted(semantic_facts, key=_priority)
    return ranked[:max_items]


def _normalize_policy_id(effect: str) -> str:
    normalized = str(effect).strip().lower()
    if not normalized:
        return "policy.unknown"
    token = normalized.split(";", 1)[0].split(" ", 1)[0]
    compact = "".join(ch for ch in token if ch.isalnum() or ch in {"_", "-", ".", ":"})
    return compact or "policy.unknown"


def _build_reasoning_trace(
    *,
    semantic_facts: list[dict[str, str]],
    policy_effects: list[str],
    contradictions: list[dict[str, Any]],
    final_label: str | None,
) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for index, row in enumerate(semantic_facts[:6]):
        path = str(row.get("path", "")).strip() or "diff context"
        span = str(row.get("line_span", "")).strip() or "unspecified"
        rule = str(row.get("rule", "")).strip() or "semantic_fact"
        target = str(row.get("target", "")).strip() or "runtime/API behavior"
        action = str(row.get("action", "")).strip() or "changed"
        implied_bump = (
            str(row.get("suggested_bump", final_label or "PATCH")).strip().upper() or "PATCH"
        )
        before_state = str(row.get("before", "")).strip() or "previous state"
        after_state = str(row.get("after", "")).strip() or action
        claims.append(
            {
                "claim_id": f"semantic:{index + 1}",
                "evidence": {"path": path, "span": span, "rule": rule},
                "policy": {
                    "id": f"semantic.{rule.lower()}",
                    "effect": f"suggested_bump={implied_bump}",
                },
                "impact": {
                    "statement": f"{target}: {before_state} -> {after_state}",
                    "implied_bump": implied_bump,
                },
            }
        )

    anchor_path = (
        str(semantic_facts[0].get("path", "")).strip() if semantic_facts else "diff context"
    )
    for index, effect in enumerate(policy_effects[:3]):
        normalized_effect = str(effect).strip()
        if not normalized_effect:
            continue
        claims.append(
            {
                "claim_id": f"policy:{index + 1}",
                "evidence": {"path": anchor_path, "span": "unspecified", "rule": "policy_effect"},
                "policy": {
                    "id": _normalize_policy_id(normalized_effect),
                    "effect": normalized_effect,
                },
                "impact": {
                    "statement": normalized_effect,
                    "implied_bump": str(final_label or "").strip().upper() or "NO_BUMP",
                },
            }
        )

    for index, contradiction in enumerate(contradictions[:3]):
        code = str(contradiction.get("code", "")).strip() or "contradiction"
        message = str(contradiction.get("message", "")).strip() or "Contradiction detected."
        raw_paths = _as_object_list(contradiction.get("evidence_paths", []))
        evidence_path = "diff context"
        if raw_paths is not None:
            for candidate in raw_paths:
                normalized = str(candidate).strip()
                if normalized:
                    evidence_path = normalized
                    break
        claims.append(
            {
                "claim_id": f"contradiction:{index + 1}",
                "evidence": {
                    "path": evidence_path,
                    "span": "unspecified",
                    "rule": "contradiction_signal",
                },
                "policy": {"id": f"contradiction.{code}", "effect": message},
                "impact": {
                    "statement": message,
                    "implied_bump": str(final_label or "").strip().upper() or "NO_BUMP",
                },
            }
        )
    return claims


def _detect_contradictions(
    *,
    event_labels: list[str],
    semantic_facts: list[dict[str, str]],
    status: str,
    final_label: str | None,
) -> list[dict[str, Any]]:
    normalized_labels = {str(label).strip().lower() for label in event_labels if str(label).strip()}
    fix_intent = any(
        token in label for label in normalized_labels for token in ("bump:patch", "fix", "bug")
    )
    no_bump_intent = any(
        label in {"bump:no-bump", "bump:no_bump", "no-bump", "no_bump", "release:none"}
        for label in normalized_labels
    )
    runtime_rows = [
        row
        for row in semantic_facts
        if str(row.get("impact_scope", "")).strip().lower() != "non_runtime"
        and str(row.get("action", "")).strip().lower() != "unchanged"
    ]
    public_change_rows = [
        row
        for row in semantic_facts
        if str(row.get("impact_scope", "")).strip().lower() == "public_api"
        and str(row.get("suggested_bump", "")).strip().upper() in {"MAJOR", "MINOR"}
    ]
    contradictions: list[dict[str, Any]] = []

    if (
        fix_intent
        and public_change_rows
        and str(final_label or "").strip().upper() in {"MAJOR", "MINOR"}
    ):
        contradictions.append(
            {
                "code": "intent_fix_vs_public_change",
                "message": (
                    "PR intent suggests fix/patch, but semantic facts indicate public API "
                    "additions or breaking changes."
                ),
                "severity": "high",
                "evidence_paths": sorted(
                    {
                        str(item.get("path", "")).strip()
                        for item in public_change_rows
                        if str(item.get("path", "")).strip()
                    }
                ),
            }
        )

    if no_bump_intent and runtime_rows:
        contradictions.append(
            {
                "code": "intent_no_bump_vs_runtime_delta",
                "message": "PR intent indicates NO_BUMP, but runtime semantic deltas were detected.",
                "severity": "high",
                "evidence_paths": sorted(
                    {
                        str(item.get("path", "")).strip()
                        for item in runtime_rows
                        if str(item.get("path", "")).strip()
                    }
                ),
            }
        )

    if (
        status == "classified"
        and str(final_label or "").strip().upper() == "NO_BUMP"
        and runtime_rows
    ):
        contradictions.append(
            {
                "code": "classified_no_bump_vs_runtime_delta",
                "message": "NO_BUMP classification conflicts with runtime semantic deltas.",
                "severity": "high",
                "evidence_paths": sorted(
                    {
                        str(item.get("path", "")).strip()
                        for item in runtime_rows
                        if str(item.get("path", "")).strip()
                    }
                ),
            }
        )

    deduped: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for item in contradictions:
        code = str(item.get("code", "")).strip()
        if not code or code in seen_codes:
            continue
        seen_codes.add(code)
        deduped.append(item)
    return deduped


def _uses_accepted_evidence_ids(
    *,
    court_advisory: dict[str, Any],
    evidence_lookup: dict[str, dict[str, str]],
) -> bool:
    accepted_ids = _as_object_list(court_advisory.get("accepted_evidence_ids"))
    if accepted_ids is None:
        return False
    normalized_ids = [str(item).strip() for item in accepted_ids if str(item).strip()]
    return any(item in evidence_lookup for item in normalized_ids)


def _reasoning_intro_for_label(label: str) -> str:
    mapping = {
        "MAJOR": "Court selected MAJOR because a breaking behavior change was detected",
        "MINOR": "Court selected MINOR because backward-compatible behavior was added",
        "PATCH": "Court selected PATCH because internal behavior was updated",
        "NO_BUMP": "Court selected NO_BUMP because changes are operational only",
    }
    return mapping.get(label.upper(), f"Court selected {label} from available evidence")


def _render_evidence_grounded_reasoning(
    *,
    advisory_label: str,
    court_advisory: dict[str, Any],
    evidence_lookup: dict[str, dict[str, str]],
) -> tuple[str | None, bool]:
    records = _select_explanation_records(
        advisory_label=advisory_label,
        court_advisory=court_advisory,
        evidence_lookup=evidence_lookup,
        max_items=3,
    )
    if not records:
        return None, False
    if _is_explanation_dsl_enabled():
        facts = explanation_dsl.build_explanation_facts(
            advisory_label=advisory_label,
            records=records,
            max_target_items=2,
        )
        if facts:
            reasoning = explanation_dsl.render_reasoning_from_facts(facts)
            if (
                reasoning
                and explanation_dsl.passes_quality_policy(reasoning)
                and _is_human_readable_explanation(reasoning)
            ):
                return reasoning, True

    paths = [
        str(record.get("path", "")).strip()
        for record in records
        if str(record.get("path", "")).strip()
    ]
    target_summary = _summarize_path_targets(paths)
    change_hint = _change_hint_from_records(records)
    detail = f", including {change_hint}" if change_hint else ""
    reasoning = f"{_reasoning_intro_for_label(advisory_label)} in {target_summary}{detail}."
    if len(reasoning) > 320:
        reasoning = reasoning[:317].rstrip() + "..."
    if not _is_human_readable_explanation(reasoning):
        return None, False
    return reasoning, True


def _render_evidence_grounded_changelog(
    *,
    advisory_label: str,
    court_advisory: dict[str, Any],
    evidence_lookup: dict[str, dict[str, str]],
) -> tuple[str | None, bool]:
    records = _select_explanation_records(
        advisory_label=advisory_label,
        court_advisory=court_advisory,
        evidence_lookup=evidence_lookup,
        max_items=3,
    )
    if not records:
        return None, False
    if _is_explanation_dsl_enabled():
        facts = explanation_dsl.build_explanation_facts(
            advisory_label=advisory_label,
            records=records,
            max_target_items=2,
        )
        if facts:
            changelog = explanation_dsl.render_changelog_from_facts(facts)
            if (
                changelog
                and explanation_dsl.passes_quality_policy(changelog)
                and _is_human_readable_explanation(changelog)
            ):
                return changelog, True

    if advisory_label == "NO_BUMP":
        return "chore: no release required", True
    paths = [
        str(record.get("path", "")).strip()
        for record in records
        if str(record.get("path", "")).strip()
    ]
    primary = records[0]
    scope = _derive_scope_from_path(paths[0] if paths else "", rule=str(primary.get("rule", "")))
    target_summary = _summarize_path_targets(paths)
    change_hint = _change_hint_from_records(records)
    detail = f" via {change_hint}" if change_hint else ""
    if advisory_label == "MAJOR":
        changelog = f"feat({scope})!: introduce breaking behavior across {target_summary}{detail}"
        return (changelog, True) if _is_human_readable_explanation(changelog) else (None, False)
    if advisory_label == "MINOR":
        changelog = f"feat({scope}): add behavior across {target_summary}{detail}"
        return (changelog, True) if _is_human_readable_explanation(changelog) else (None, False)
    if advisory_label == "PATCH":
        changelog = f"fix({scope}): update behavior across {target_summary}{detail}"
        return (changelog, True) if _is_human_readable_explanation(changelog) else (None, False)
    return None, False


def _is_generic_court_summary(summary: str, *, label: str | None) -> bool:
    normalized = summary.strip()
    if not normalized:
        return True
    lowered = normalized.lower()
    if lowered == "compatibility court selected the final semver classification.":
        return True
    normalized_label = str(label or "").strip().upper()
    return bool(
        normalized_label
        and lowered
        == f"court selected {normalized_label.lower()} based on the strongest evidence in the case file."
    )


def _prefer_deterministic_explanation(
    *,
    court_advisory: dict[str, Any],
    advisory_label: str | None,
) -> bool:
    confidence = str(court_advisory.get("confidence", "")).strip().lower()
    summary = str(court_advisory.get("judge_summary", "")).strip()
    return confidence == "low" or _is_generic_court_summary(summary, label=advisory_label)


def _select_court_reasoning(
    *,
    court_advisory: dict[str, Any],
    advisory_label: str | None,
    pre_court_result: dict[str, Any],
) -> tuple[str, bool]:
    court_summary = str(court_advisory.get("judge_summary", "")).strip()
    deterministic_reasoning = str(pre_court_result.get("reasoning", "")).strip()
    if (
        _prefer_deterministic_explanation(
            court_advisory=court_advisory, advisory_label=advisory_label
        )
        and deterministic_reasoning
    ):
        return deterministic_reasoning, True
    if court_summary:
        return court_summary, False
    if deterministic_reasoning:
        return deterministic_reasoning, True
    return "Compatibility court selected the final SemVer classification.", False


def _select_court_changelog(
    *,
    advisory_label: str,
    court_advisory: dict[str, Any],
    pre_court_result: dict[str, Any],
) -> tuple[str, bool]:
    deterministic_label = str(pre_court_result.get("label", "")).strip().upper()
    deterministic_changelog = str(pre_court_result.get("changelog", "")).strip()
    if (
        deterministic_label == advisory_label
        and deterministic_changelog
        and _prefer_deterministic_explanation(
            court_advisory=court_advisory,
            advisory_label=advisory_label,
        )
    ):
        return deterministic_changelog, True
    return _changelog_for_label(advisory_label), False


def _apply_docs_only_policy(
    result: dict[str, object],
    bumpkin_config: BumpkinConfig,
    notes: list[str],
) -> dict[str, object]:
    if str(result.get("status", "classified")) != "classified":
        return result
    if str(result.get("label", "")).upper() != "NO_BUMP":
        return result
    if bumpkin_config.docs_only_label != "PATCH":
        return result

    updated = dict(result)
    updated["label"] = "PATCH"
    updated["changelog"] = "chore: release required by repo policy"
    notes.append("Repository policy remapped NO_BUMP to PATCH via docs_only_label=PATCH.")
    return updated


def _should_skip_court_advisory(
    *,
    status: str,
    deterministic_label: str | None,
    deterministic_confidence: str | None,
    mode_used: str,
    classification_source: str,
) -> tuple[bool, str | None]:
    if status != "classified" or not deterministic_label:
        return False, None

    normalized_label = deterministic_label.upper()
    normalized_confidence = str(deterministic_confidence or "").strip().lower()
    normalized_mode = mode_used.strip().lower()
    normalized_source = classification_source.strip().lower()
    degraded_path = normalized_mode.startswith("fallback") or "degraded" in normalized_source

    if degraded_path:
        return False, None

    # Confidence is authoritative for court invocation policy:
    # anything below high must call court regardless of label.
    if normalized_confidence == "high":
        return True, f"deterministic_high_confidence_{normalized_label.lower()}"

    return False, None


def _build_skipped_court_advisory(
    *,
    deterministic_label: str | None,
    deterministic_confidence: str | None,
    court_skipped_reason: str,
) -> dict[str, Any]:
    skipped_label = deterministic_label or "deterministic"
    return {
        "status": "skipped",
        "label": deterministic_label,
        "confidence": deterministic_confidence or "high",
        "judge_summary": (
            f"Court advisory skipped ({court_skipped_reason}) for deterministic {skipped_label}."
        ),
        "prosecutor_claims": [],
        "defender_claims": [],
        "accepted_arguments": [
            f"Deterministic {skipped_label} decision accepted without court call."
        ],
        "rejected_arguments": [],
        "unresolved_risks": [],
        "accepted_evidence_ids": [],
        "rejected_evidence_ids": [],
        "disagreement_reason": None,
    }


def analyze_diff_core(
    *,
    diff_result: DiffResult,
    mode: str,
    model: str,
    fallback_model: str | None,
    endpoint: str,
    token: str,
    max_retries: int,
    request_timeout: int,
    prompt_metadata: PromptPackMetadata,
    bumpkin_config: BumpkinConfig,
    planner_decision: PlannerDecision,
    notes: list[str] | None = None,
    event_labels: list[str] | None = None,
    scope_mismatch_detected: bool = False,
    scope_mismatch_reason: str | None = None,
    scope_guard: dict[str, object] | None = None,
    public_api_hints: list[str] | None = None,
    language_hints: list[str] | None = None,
) -> CoreAnalysisResult:
    local_notes = list(notes or [])
    labels = list(event_labels or [])
    local_public_hints = policy_engine.dedupe_preserving_order(list(public_api_hints or []))
    local_scope_guard = dict(scope_guard or {})

    behavior_contract_signals = policy_engine.detect_behavior_contract_signals(
        diff_result.analyzed_files,
        policy=bumpkin_config.behavior_contract_policy,
    )
    workspace_loader = _workspace_loader_for_diff_result(diff_result)
    findings = (
        detect_semver_findings(
            diff_result.full_diff_text,
            workspace_loader=workspace_loader,
        )
        if diff_result.full_diff_text and not scope_mismatch_detected
        else []
    )
    evidence_items = build_evidence_items(
        findings=findings,
        diff_text=diff_result.full_diff_text,
        behavior_contract_signals=behavior_contract_signals,
    )
    evidence_summary_meta = summarize_evidence_items(evidence_items)
    if evidence_items:
        local_notes.append(f"Evidence extraction produced {len(evidence_items)} item(s).")

    fallback_reason: str | None = None
    mode_used = "deterministic-engine"
    model_used: str | None = None
    classification_source = "deterministic-engine"
    chunking_meta: dict[str, object] = {
        "enabled": bool(bumpkin_config.chunking_enabled),
        "chunk_count": 0,
        "succeeded": 0,
        "failed": 0,
        "skipped": 0,
        "max_chunk_tokens": bumpkin_config.chunk_max_tokens,
        "max_chunk_count": bumpkin_config.chunk_max_count,
        "failure_policy": bumpkin_config.chunk_failure_policy,
        "files_total": len(diff_result.analyzed_files),
        "files_covered": len(diff_result.analyzed_files),
        "files_omitted": 0,
        "omitted_files": [],
        "omitted_files_sample": [],
    }
    aggregation_trace: str | None = None
    boundary_summary = {"public": 0, "internal": 0, "unknown": 0}
    coverage_contract: dict[str, object] = {
        "version": "coverage_contract_v1",
        "status": "pass",
        "critical_files_total": 0,
        "critical_files_covered": 0,
        "omitted_critical_files": [],
        "omitted_files_total": 0,
    }
    policy_actions: list[str] = []
    coverage_guard_triggered = False

    if scope_mismatch_detected:
        result: dict[str, object] = {
            "status": "manual_review",
            "label": None,
            "confidence": None,
            "reasoning": "Analysis could not be reliably scoped to PR files.",
            "changelog": None,
        }
        mode_used = "scope-guard"
        model_used = "scope-guard"
        fallback_reason = scope_mismatch_reason
        classification_source = "scope-mismatch-guard"
    elif diff_result.diff_text:
        aggregated_findings = aggregate_findings(findings)
        if mode.strip().lower() == "stub":
            result = get_stub_recommendation(truncated=diff_result.truncated)
            mode_used = "stub"
            model_used = "stub"
            classification_source = orchestrator_adjudication.source_from_mode(mode_used)
        elif aggregated_findings is not None:
            result = aggregated_findings.to_result_dict()
            aggregation_trace = aggregated_findings.aggregation_trace
            mode_used = "deterministic-findings"
            classification_source = "deterministic-findings"
            local_notes.append("Deterministic findings engine produced base classification.")
        else:
            result = semantic_fallback_recommendation(
                diff_text=diff_result.diff_text,
                surface_area_hints=local_public_hints,
                truncated=diff_result.truncated,
            )
            mode_used = "deterministic-heuristic"
            classification_source = "deterministic-heuristic"
            local_notes.append("Deterministic semantic heuristic produced base classification.")
    else:
        result = get_no_bump_recommendation(truncated=diff_result.truncated)
        mode_used = "deterministic-no-diff"
        model_used = "heuristic"
        classification_source = "deterministic-no-diff"

    if not scope_mismatch_detected:
        aggregated_findings = aggregate_findings(findings)
        result, aggregation_trace, classification_source = (
            orchestrator_adjudication.apply_findings_adjudication(
                result,
                aggregated_findings=aggregated_findings,
                mode_used=mode_used,
                notes=local_notes,
            )
        )
        boundary_summary = policy_engine.summarize_boundary(
            findings, public_hints=local_public_hints
        )
        result, coverage_guard_triggered = guard_policies.apply_analysis_coverage_guard(
            result,
            analyzed_files=diff_result.analyzed_files,
            findings=findings,
            chunking_meta=chunking_meta,
            notes=local_notes,
        )
        if coverage_guard_triggered:
            classification_source = "coverage-guard"

    evidence_summary = policy_engine.summarize_evidence(
        findings,
        public_hints=local_public_hints,
        contract_signals=behavior_contract_signals,
    )
    non_actionable_noise_ratio = 0.0
    if diff_result.changed_files_total > 0:
        non_actionable_noise_ratio = round(
            diff_result.ignored_files_total / diff_result.changed_files_total,
            4,
        )

    result, policy_mode_effects, policy_actions = policy_engine.apply_policy_mode(
        result,
        boundary_summary=boundary_summary,
        config=bumpkin_config,
        notes=local_notes,
    )
    result, unknown_boundary_effects, unknown_boundary_actions = (
        policy_engine.apply_unknown_boundary_policy(
            result,
            boundary_summary=boundary_summary,
            config=bumpkin_config,
            notes=local_notes,
        )
    )
    policy_actions.extend(unknown_boundary_actions)
    result, impact_threshold_effects, impact_threshold_actions = (
        policy_engine.apply_impact_evidence_threshold(
            result,
            boundary_summary=boundary_summary,
            evidence_summary=evidence_summary,
            config=bumpkin_config,
            notes=local_notes,
        )
    )
    policy_actions.extend(impact_threshold_actions)
    result, noise_policy_effects, noise_policy_actions = (
        policy_engine.apply_noise_suppression_policy(
            result,
            noise_ratio=non_actionable_noise_ratio,
            changed_files_total=diff_result.changed_files_total,
            evidence_summary=evidence_summary,
            config=bumpkin_config,
            notes=local_notes,
        )
    )
    policy_actions.extend(noise_policy_actions)
    if findings:
        local_notes.append(
            "Boundary summary: "
            f"public={boundary_summary['public']}, "
            f"internal={boundary_summary['internal']}, "
            f"unknown={boundary_summary['unknown']}."
        )

    result, truncated_no_bump_guard_triggered = guard_policies.apply_truncated_no_bump_guard(
        result,
        truncated=diff_result.truncated,
        analyzed_files=diff_result.analyzed_files,
        policy=bumpkin_config.truncated_no_bump_policy,
        notes=local_notes,
    )
    result, surface_area_guard_triggered = guard_policies.apply_truncated_surface_area_guard(
        result,
        truncated=diff_result.truncated,
        analyzed_files=diff_result.analyzed_files,
        surface_area_hints=local_public_hints,
        chunking_meta=chunking_meta,
        notes=local_notes,
    )
    result, large_pr_guard_triggered = guard_policies.apply_large_pr_no_bump_guard(
        result,
        analyzed_files_count=len(diff_result.analyzed_files),
        approx_prompt_tokens=diff_result.approx_prompt_tokens,
        max_files=bumpkin_config.large_pr_max_files,
        max_tokens=bumpkin_config.large_pr_max_tokens,
        policy=bumpkin_config.truncated_no_bump_policy,
        notes=local_notes,
    )

    coverage_contract = build_coverage_contract(
        analyzed_files=diff_result.analyzed_files,
        chunking_meta=chunking_meta,
        public_api_hints=local_public_hints,
        behavior_contract_signals=behavior_contract_signals,
    )
    if coverage_contract["status"] == "fail":
        local_notes.append(
            "Coverage contract failed: omitted critical files require manual review."
        )
        if str(result.get("status", "classified")) == "classified":
            result = {
                "status": "manual_review",
                "label": None,
                "confidence": None,
                "reasoning": (
                    "Critical coverage requirements were not met. "
                    "Manual review is required before SemVer classification."
                ),
                "changelog": None,
            }
            classification_source = "coverage-contract"
            coverage_guard_triggered = True

    status_before_policy = str(result.get("status", "classified"))
    label_before_policy = (
        str(result.get("label", "")).upper() if status_before_policy == "classified" else None
    )
    policy_effects: list[str] = (
        list(policy_mode_effects)
        + list(unknown_boundary_effects)
        + list(impact_threshold_effects)
        + list(noise_policy_effects)
    )
    policy_effects.append(
        policy_engine.derive_docs_only_policy_effect(
            status=status_before_policy,
            label=label_before_policy,
            docs_only_label=bumpkin_config.docs_only_label,
        )
    )
    result = _apply_docs_only_policy(result, bumpkin_config, local_notes)

    result, degraded_policy_effects, degraded_policy_actions = (
        policy_engine.apply_degraded_provider_policy(
            result,
            mode_used=mode_used,
            classification_source=classification_source,
            config=bumpkin_config,
            notes=local_notes,
        )
    )
    policy_actions.extend(degraded_policy_actions)
    policy_effects.extend(degraded_policy_effects)

    status = str(result.get("status", "classified"))
    if status not in {"classified", "manual_review"}:
        status = "manual_review"
    analysis_state, classification_source = orchestrator_adjudication.derive_analysis_state(
        status=status,
        classification_source=classification_source,
    )
    failure_category = orchestrator_adjudication.categorize_failure_reason(fallback_reason)

    if mode_used == "deterministic-findings":
        local_notes.append("Deterministic findings selected the base SemVer classification.")
    elif mode_used == "deterministic-heuristic":
        local_notes.append(
            "Deterministic semantic heuristic selected the base SemVer classification."
        )
    elif mode_used == "deterministic-no-diff":
        local_notes.append(
            "No diff content detected; deterministic NO_BUMP classification applied."
        )
    elif mode_used == "scope-guard":
        local_notes.append(
            "Scope mismatch guard blocked automated classification; manual review required."
        )
    elif mode_used == "stub":
        local_notes.append("Stub mode selected for deterministic base classification.")
    if not planner_decision.allow_model_call:
        local_notes.append(
            f"Planner blocked provider usage for advisory path (reason={planner_decision.reason})."
        )
    if status == "manual_review":
        local_notes.append("No authoritative SemVer classification was produced.")
    local_notes.append(f"Analysis state: {analysis_state} (source={classification_source}).")
    if failure_category:
        local_notes.append(f"Failure category: {failure_category}.")
    local_notes.append(
        "Prompt pack: "
        f"{prompt_metadata.prompt_version} "
        f"(language_group={prompt_metadata.language_group}, "
        f"promotion_status={prompt_metadata.promotion_status})."
    )

    impact_summary = summarize_impact(diff_result.full_diff_text).to_dict()

    finalization = orchestrator_finalize.finalize_release(
        result=result,
        status=status,
        status_before_policy=status_before_policy,
        label_before_policy=label_before_policy,
        findings=findings,
        aggregation_trace=aggregation_trace,
        boundary_summary=boundary_summary,
        evidence_summary=evidence_summary,
        behavior_contract_signals=behavior_contract_signals,
        non_actionable_noise_ratio=non_actionable_noise_ratio,
        diff_result=diff_result,
        bumpkin_config=bumpkin_config,
        event_labels=labels,
        notes=local_notes,
        policy_effects=policy_effects,
        policy_actions=policy_actions,
        planner_payload=planner_decision.to_dict(),
        coverage_contract=coverage_contract,
    )
    result = finalization.result
    local_notes = finalization.notes
    policy_effects = finalization.policy_effects
    override_summary = finalization.override_summary
    override_status = finalization.override_status
    override_payload = finalization.override_payload
    current_tag = finalization.current_tag
    next_tag = finalization.next_tag
    decision_trace = finalization.decision_trace

    case_file_build = build_case_file(
        engine_result=result,
        findings=findings,
        evidence_items=evidence_items,
        policy_effects=policy_effects,
        notes=local_notes,
        coverage_contract=coverage_contract,
        boundary_summary=boundary_summary,
        evidence_summary=evidence_summary,
    )
    case_file = case_file_build.case_file
    case_file_stats = case_file_build.stats
    pre_court_result = dict(result)
    pre_court_status = str(pre_court_result.get("status", "manual_review"))
    deterministic_label = (
        str(pre_court_result.get("label", "")).upper() if pre_court_status == "classified" else None
    )
    deterministic_confidence = str(pre_court_result.get("confidence", "")).strip().lower() or None
    deterministic_next_tag = next_tag if pre_court_status == "classified" else None
    advisory_token = token if planner_decision.allow_model_call else ""

    should_skip_court, court_skipped_reason = _should_skip_court_advisory(
        status=pre_court_status,
        deterministic_label=deterministic_label,
        deterministic_confidence=deterministic_confidence,
        mode_used=mode_used,
        classification_source=classification_source,
    )
    if should_skip_court and court_skipped_reason:
        court_advisory = _build_skipped_court_advisory(
            deterministic_label=deterministic_label,
            deterministic_confidence=deterministic_confidence,
            court_skipped_reason=court_skipped_reason,
        )
        court_fallback_reason = None
        court_model_used = None
        local_notes.append(f"Court advisory skipped: {court_skipped_reason}.")
    else:
        court_skipped_reason = None
        court_advisory, court_fallback_reason, court_model_used = (
            orchestrator_court.run_court_advisory(
                mode=mode,
                model=model,
                fallback_model=fallback_model or None,
                endpoint=endpoint,
                token=advisory_token,
                max_retries=max_retries,
                request_timeout=request_timeout,
                engine_label=deterministic_label,
                case_file_text=render_case_file_text(case_file),
                language_hints=language_hints,
            )
        )

    if court_model_used:
        local_notes.append(f"Compatibility court analyzed by model: {court_model_used}.")
    if court_fallback_reason:
        local_notes.append(f"Compatibility court advisory degraded: {court_fallback_reason}.")
    if str(court_advisory.get("status", "")).lower() == "manual_review":
        reason = str(court_advisory.get("disagreement_reason", "")).strip()
        if reason:
            local_notes.append(reason)

    decision_authority = bumpkin_config.decision_authority_mode
    if decision_authority == "court":
        advisory_status = str(court_advisory.get("status", "")).strip().lower()
        advisory_label = str(court_advisory.get("label", "")).strip().upper()
        if advisory_status in {"aligned", "manual_review"} and advisory_label in {
            "MAJOR",
            "MINOR",
            "PATCH",
            "NO_BUMP",
        }:
            evidence_lookup = _case_file_evidence_lookup(case_file)
            using_accepted_evidence_ids = _uses_accepted_evidence_ids(
                court_advisory=court_advisory,
                evidence_lookup=evidence_lookup,
            )
            selected_records = _select_explanation_records(
                advisory_label=advisory_label,
                court_advisory=court_advisory,
                evidence_lookup=evidence_lookup,
                max_items=3,
            )
            selected_reasoning, used_evidence_reasoning = _render_evidence_grounded_reasoning(
                advisory_label=advisory_label,
                court_advisory=court_advisory,
                evidence_lookup=evidence_lookup,
            )
            selected_changelog, used_evidence_changelog = _render_evidence_grounded_changelog(
                advisory_label=advisory_label,
                court_advisory=court_advisory,
                evidence_lookup=evidence_lookup,
            )
            used_deterministic_reasoning = False
            used_deterministic_changelog = False
            if not selected_reasoning:
                selected_reasoning, used_deterministic_reasoning = _select_court_reasoning(
                    court_advisory=court_advisory,
                    advisory_label=advisory_label,
                    pre_court_result=pre_court_result,
                )
            if not selected_changelog:
                selected_changelog, used_deterministic_changelog = _select_court_changelog(
                    advisory_label=advisory_label,
                    court_advisory=court_advisory,
                    pre_court_result=pre_court_result,
                )
            polish_applied = False
            polish_failure_reason: str | None = None
            confidence_text = str(court_advisory.get("confidence", "low")).strip().lower() or "low"
            if _should_run_explanation_polish(
                reasoning=selected_reasoning,
                changelog=selected_changelog,
                confidence=confidence_text,
                token=advisory_token,
            ):
                polish_reasoning, polish_changelog, polish_applied, polish_failure_reason = (
                    _polish_explanation_with_model(
                        advisory_label=advisory_label,
                        draft_reasoning=selected_reasoning,
                        draft_changelog=selected_changelog,
                        records=selected_records,
                        token=advisory_token,
                        endpoint=endpoint,
                        model=court_model_used or model,
                        max_retries=max_retries,
                        request_timeout=request_timeout,
                    )
                )
                selected_reasoning = polish_reasoning
                selected_changelog = polish_changelog
            explicit_regenerated = False
            selected_reasoning, selected_changelog, explicit_regenerated = (
                _enforce_explicit_explanation(
                    advisory_label=advisory_label,
                    reasoning=selected_reasoning,
                    changelog=selected_changelog,
                    records=selected_records,
                    fallback_paths=diff_result.analyzed_files,
                )
            )
            result = {
                "status": "classified",
                "label": advisory_label,
                "confidence": confidence_text,
                "reasoning": selected_reasoning,
                "changelog": selected_changelog,
            }
            status = "classified"
            classification_source = "court"
            analysis_state = "authoritative"
            failure_category = None
            if used_deterministic_reasoning:
                local_notes.append(
                    "Court authority reused deterministic reasoning because court explanation was generic or low-confidence."
                )
            elif used_evidence_reasoning:
                if using_accepted_evidence_ids:
                    local_notes.append(
                        "Court authority generated reasoning from accepted evidence IDs."
                    )
                else:
                    local_notes.append(
                        "Court authority generated reasoning from deterministic evidence fallback records."
                    )
            if used_deterministic_changelog:
                local_notes.append(
                    "Court authority reused deterministic changelog because court explanation was generic or low-confidence."
                )
            elif used_evidence_changelog:
                if using_accepted_evidence_ids:
                    local_notes.append(
                        "Court authority generated changelog from accepted evidence IDs."
                    )
                else:
                    local_notes.append(
                        "Court authority generated changelog from deterministic evidence fallback records."
                    )
            if polish_applied:
                local_notes.append("Applied low-token explanation polish pass for readability.")
            elif polish_failure_reason:
                local_notes.append(
                    f"Explanation polish skipped/failed; kept deterministic wording ({polish_failure_reason})."
                )
            if explicit_regenerated:
                local_notes.append(
                    "Explicitness gate regenerated reasoning/changelog to include concrete file anchors and action verbs."
                )
            if advisory_label != deterministic_label:
                local_notes.append(
                    f"Court authority applied: deterministic {deterministic_label} -> court {advisory_label}."
                )
            if advisory_label != "NO_BUMP":
                current_tag, next_tag, court_version_notes = detect_next_version(
                    advisory_label,
                    pre_1_0_breaking_as_minor=bumpkin_config.pre_1_0_breaking_as_minor,
                )
                local_notes.extend(court_version_notes)
            else:
                next_tag = None
        elif advisory_status in {"degraded", "skipped"} and pre_court_status == "classified":
            result = pre_court_result
            status = "classified"
            classification_source = "deterministic-court-fallback"
            analysis_state = (
                "degraded_fallback" if advisory_status == "degraded" else "authoritative"
            )
            if advisory_status == "degraded":
                failure_category = (
                    orchestrator_adjudication.categorize_failure_reason(court_fallback_reason)
                    or failure_category
                )
            next_tag = deterministic_next_tag
            if advisory_status == "degraded":
                local_notes.append(
                    "Court authority degraded; using pre-court deterministic classification as fallback."
                )
            else:
                local_notes.append(
                    "Court authority skipped; using pre-court deterministic classification."
                )
        else:
            result = {
                "status": "manual_review",
                "label": None,
                "confidence": None,
                "reasoning": (
                    "Compatibility court is configured as final authority, but no reliable court verdict "
                    "was available. Manual review is required."
                ),
                "changelog": None,
            }
            status = "manual_review"
            classification_source = "court-unavailable"
            analysis_state = "manual_review"
            next_tag = None
            local_notes.append(
                "Court authority mode forced manual review because advisory status was not authoritative."
            )

    explainability_rows: list[dict[str, str]] = []
    if status == "classified":
        final_label = str(result.get("label", "")).strip().upper()
        evidence_lookup_for_rows = _case_file_evidence_lookup(case_file)
        explainability_rows = _build_explainability_rows(
            advisory_label=final_label,
            court_advisory=court_advisory,
            evidence_lookup=evidence_lookup_for_rows,
            analyzed_files=diff_result.analyzed_files,
            diff_text=diff_result.full_diff_text,
            max_items=8,
        )
        semantic_rows = explanation_dsl.filter_semantic_delta_rows(explainability_rows)
        if not semantic_rows:
            result = {
                "status": "manual_review",
                "label": None,
                "confidence": None,
                "reasoning": (
                    "Explainability contract is unsatisfied because deterministic DSL "
                    "did not emit semantic delta rows. Manual review is required."
                ),
                "changelog": None,
            }
            status = "manual_review"
            classification_source = "explainability-contract"
            analysis_state = "manual_review"
            failure_category = "explainability_semantic_contract_unsatisfied"
            next_tag = None
            explainability_rows = []
            local_notes.append(
                "Fail-closed explainability gate triggered: only path-level or empty explainability rows were available."
            )
        else:
            explainability_rows = semantic_rows

    semantic_facts = explanation_dsl.filter_semantic_delta_rows(explainability_rows)
    evaluated_label_for_obligations = (
        str(result.get("label", "")).strip().upper()
        if status == "classified"
        else (str(court_advisory.get("label", "")).strip().upper() or deterministic_label)
    )
    proof_obligations = _evaluate_proof_obligations(
        status=status,
        evaluated_label=evaluated_label_for_obligations,
        semantic_facts=semantic_facts,
    )
    critical_missing_obligations = _critical_missing_proof_obligations(proof_obligations)
    if status == "classified" and critical_missing_obligations:
        result = {
            "status": "manual_review",
            "label": None,
            "confidence": None,
            "reasoning": (
                "Proof-obligation contract is unsatisfied because critical obligations are missing "
                f"({', '.join(critical_missing_obligations)}). Manual review is required."
            ),
            "changelog": None,
        }
        status = "manual_review"
        classification_source = "proof-obligation-contract"
        analysis_state = "manual_review"
        failure_category = failure_category or "proof_obligation_contract_unsatisfied"
        next_tag = None
        local_notes.append(
            "Fail-closed proof-obligation gate triggered: classified output downgraded to manual_review."
        )
    proof_obligations["status"] = status
    final_label_for_trace = (
        str(result.get("label", "")).strip().upper() if status == "classified" else None
    )
    contradictions = _detect_contradictions(
        event_labels=labels,
        semantic_facts=semantic_facts,
        status=status,
        final_label=final_label_for_trace,
    )
    semantic_facts = _prioritize_semantic_facts(
        semantic_facts,
        contradiction_paths=_extract_contradiction_paths(contradictions),
        max_items=8,
    )
    if status == "classified":
        explainability_rows = list(semantic_facts)
    reasoning_trace = _build_reasoning_trace(
        semantic_facts=semantic_facts,
        policy_effects=policy_effects,
        contradictions=contradictions,
        final_label=final_label_for_trace,
    )

    decision_trace["decision_authority"] = decision_authority
    decision_trace["deterministic_label"] = deterministic_label
    decision_trace["deterministic_next_tag"] = deterministic_next_tag
    decision_trace["court_skipped_reason"] = court_skipped_reason
    decision_trace["explainability_rows"] = len(explainability_rows)
    decision_trace["court"] = {
        "status": court_advisory.get("status"),
        "label": court_advisory.get("label"),
        "confidence": court_advisory.get("confidence"),
    }
    decision_trace["proof_obligations_missing"] = len(proof_obligations.get("missing", []))
    decision_trace["reasoning_trace_claims"] = len(reasoning_trace)
    decision_trace["contradiction_count"] = len(contradictions)

    output = orchestrator_finalize.build_output_payload(
        status=status,
        mode_used=mode_used,
        prompt_metadata=prompt_metadata,
        model_used=model_used,
        analysis_state=analysis_state,
        classification_source=classification_source,
        failure_category=failure_category,
        fallback_reason=fallback_reason,
        diff_result=diff_result,
        result=result,
        findings=findings,
        aggregation_trace=aggregation_trace,
        boundary_summary=boundary_summary,
        decision_trace=decision_trace,
        policy_effects=policy_effects,
        override_payload=override_payload,
        impact_summary=impact_summary,
        evidence_summary=evidence_summary,
        behavior_contract_signals=behavior_contract_signals,
        scope_mismatch_detected=scope_mismatch_detected,
        coverage_guard_triggered=coverage_guard_triggered,
        truncated_no_bump_guard_triggered=truncated_no_bump_guard_triggered,
        surface_area_guard_triggered=surface_area_guard_triggered,
        large_pr_guard_triggered=large_pr_guard_triggered,
        scope_guard=local_scope_guard,
        non_actionable_noise_ratio=non_actionable_noise_ratio,
        chunking_meta=chunking_meta,
        planner_payload=planner_decision.to_dict(),
        coverage_contract=coverage_contract,
        evidence_items=[item.to_dict() for item in evidence_items],
        evidence_summary_meta=evidence_summary_meta,
        case_file=case_file,
        case_file_stats=case_file_stats,
        advisory=court_advisory,
        decision_authority=decision_authority,
        deterministic_label=deterministic_label,
        deterministic_next_tag=deterministic_next_tag,
        current_tag=current_tag,
        next_tag=next_tag,
        explainability_rows=explainability_rows,
        semantic_facts=semantic_facts,
        proof_obligations=proof_obligations,
        reasoning_trace=reasoning_trace,
        contradictions=contradictions,
        notes=local_notes,
    )
    output["court_skipped_reason"] = court_skipped_reason
    output["court_fallback_reason"] = court_fallback_reason

    return CoreAnalysisResult(
        output=output,
        result=result,
        notes=local_notes,
        findings=findings,
        mode_used=mode_used,
        fallback_reason=fallback_reason,
        current_tag=current_tag,
        next_tag=next_tag,
        override_summary=override_summary,
        override_status=override_status,
        aggregation_trace=aggregation_trace,
        boundary_summary=boundary_summary,
        analysis_state=analysis_state,
        classification_source=classification_source,
        failure_category=failure_category,
        policy_effects=policy_effects,
        decision_trace=decision_trace,
        court_advisory=court_advisory,
        court_fallback_reason=court_fallback_reason,
        court_model_used=court_model_used,
        court_skipped_reason=court_skipped_reason,
        deterministic_label=deterministic_label,
        deterministic_next_tag=deterministic_next_tag,
        model_used=model_used,
        explainability_rows=explainability_rows,
        proof_obligations=proof_obligations,
        reasoning_trace=reasoning_trace,
        contradictions=contradictions,
    )
