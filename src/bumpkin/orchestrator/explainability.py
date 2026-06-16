from __future__ import annotations

import os
import re
from typing import Any, cast

from bumpkin.analysis import explanation_facts as explanation_dsl
from bumpkin.orchestrator import explanation_polish

CHANGELOG_PATTERN = explanation_polish.CHANGELOG_PATTERN
_is_human_readable_explanation = explanation_polish.is_human_readable_explanation


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
    records: list[dict[str, str]],
    fallback_paths: list[str],
) -> list[dict[str, str]]:
    merged = list(records)
    existing_paths = {
        str(record.get("path", "")).strip().lower()
        for record in merged
        if str(record.get("path", "")).strip()
    }
    for path in fallback_paths:
        normalized = str(path).strip()
        if not normalized or normalized.lower() in existing_paths:
            continue
        existing_paths.add(normalized.lower())
        merged.append(
            {
                "evidence_id": f"path_fallback:{normalized}",
                "rule": "changed_file_path",
                "path": normalized,
                "snippet": normalized,
            }
        )
    if not merged:
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


changelog_for_label = _changelog_for_label
case_file_evidence_lookup = _case_file_evidence_lookup
derive_scope_from_path = _derive_scope_from_path
summarize_path_targets = _summarize_path_targets
extract_symbol_hint = _extract_symbol_hint
derive_operation_hint = _derive_operation_hint
change_hint_from_records = _change_hint_from_records
file_anchors_from_records = _file_anchors_from_records
merge_anchor_records = _merge_anchor_records
contains_action_verb = _contains_action_verb
is_template_reasoning = _is_template_reasoning
passes_explicitness_gate = _passes_explicitness_gate
build_explicit_fallback_explanation = _build_explicit_fallback_explanation
enforce_explicit_explanation = _enforce_explicit_explanation
evidence_priority = _evidence_priority
select_explanation_records = _select_explanation_records
is_non_runtime_path = _is_non_runtime_path
extract_before_after_by_path = _extract_before_after_by_path
build_patch_fallback_records = _build_patch_fallback_records
build_no_bump_invariance_records = _build_no_bump_invariance_records
build_explainability_rows = _build_explainability_rows
row_has_semantic_transition = _row_has_semantic_transition
row_satisfies_patch_transition = _row_satisfies_patch_transition
evaluate_proof_obligations = _evaluate_proof_obligations
critical_missing_proof_obligations = _critical_missing_proof_obligations
