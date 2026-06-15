from __future__ import annotations

import fnmatch
import re

from bumpkin.analysis.findings import Finding
from bumpkin.config import BumpkinConfig
from bumpkin.versioning.tags import parse_tag

from .guards import is_docs_or_config_path


def _to_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def derive_docs_only_policy_effect(
    *,
    status: str,
    label: str | None,
    docs_only_label: str,
) -> str:
    normalized_label = str(label or "").upper()
    if docs_only_label == "NO_BUMP":
        return "docs_only_label=NO_BUMP (default)."
    if status != "classified":
        return "docs_only_label=PATCH configured; no remap applied (no base recommendation)."
    if normalized_label == "NO_BUMP":
        return "docs_only_label=PATCH applied: remapped NO_BUMP -> PATCH."
    return (
        "docs_only_label=PATCH configured; no remap applied "
        f"(base label={normalized_label or 'unknown'})."
    )


def derive_pre_1_0_policy_effect(
    *,
    status: str,
    label: str | None,
    current_tag: str | None,
    pre_1_0_breaking_as_minor: bool,
) -> str | None:
    if status != "classified":
        return (
            "pre_1_0_breaking_as_minor="
            f"{str(pre_1_0_breaking_as_minor).lower()} configured; "
            "no effect (no authoritative label)."
        )
    normalized_label = str(label or "").upper()
    if normalized_label != "MAJOR":
        return (
            "pre_1_0_breaking_as_minor="
            f"{str(pre_1_0_breaking_as_minor).lower()} configured; "
            f"no effect (label={normalized_label or 'unknown'})."
        )
    parsed = parse_tag(current_tag or "") if current_tag else None
    if not parsed or parsed.scheme != "zero-based":
        return (
            "pre_1_0_breaking_as_minor="
            f"{str(pre_1_0_breaking_as_minor).lower()} configured; "
            "no effect (tag scheme is not zero-based)."
        )
    if pre_1_0_breaking_as_minor:
        return "pre_1_0_breaking_as_minor=true applied: MAJOR treated as minor bump before 1.0.0."
    return "pre_1_0_breaking_as_minor=false applied: MAJOR used strict 1.0.0 semantics."


def dedupe_preserving_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def path_matches_hints(path: str, hints: list[str]) -> bool:
    normalized = path.strip().strip("/")
    if not normalized:
        return False
    for hint in hints:
        pattern = hint.strip().strip("/")
        if not pattern:
            continue
        if fnmatch.fnmatch(normalized, pattern):
            return True
        prefix = pattern.replace("**", "").rstrip("/")
        if prefix and normalized.startswith(prefix):
            return True
    return False


def classify_finding_boundary(finding: Finding, *, public_hints: list[str]) -> str:
    evidence = finding.evidence
    if not evidence:
        return "unknown"
    if finding.rule == "python_requires_floor_raised":
        return "public"
    first = evidence[0]
    path = str(first.get("path", "")).strip()
    if not path:
        return "unknown"
    if is_docs_or_config_path(path):
        return "internal"
    if not public_hints:
        return "unknown"
    if path_matches_hints(path, public_hints):
        return "public"
    return "internal"


def summarize_boundary(findings: list[Finding], *, public_hints: list[str]) -> dict[str, int]:
    summary = {"public": 0, "internal": 0, "unknown": 0}
    for finding in findings:
        boundary = classify_finding_boundary(finding, public_hints=public_hints)
        summary[boundary] = summary.get(boundary, 0) + 1
    return summary


def finding_severity_counts(findings: list[Finding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in findings:
        key = finding.severity.upper()
        counts[key] = counts.get(key, 0) + 1
    return counts


def has_bugfix_intent(result: dict[str, object]) -> bool:
    changelog = str(result.get("changelog") or "").strip().lower()
    if changelog.startswith("fix:"):
        return True
    reasoning = str(result.get("reasoning") or "").strip().lower()
    signals = ("bug fix", "bugfix", "fix", "regression", "internal", "refactor", "hotfix")
    return any(token in reasoning for token in signals)


def apply_policy_mode(
    result: dict[str, object],
    *,
    boundary_summary: dict[str, int],
    config: BumpkinConfig,
    notes: list[str],
) -> tuple[dict[str, object], list[str], list[str]]:
    policy_effects: list[str] = []
    policy_actions: list[str] = []
    status = str(result.get("status", "classified"))
    if status != "classified":
        policy_effects.append(
            f"policy_mode={config.policy_mode} configured; no effect (status={status})."
        )
        return result, policy_effects, policy_actions

    policy_effects.append(
        f"policy_mode={config.policy_mode}; bugfix_patch_bias={str(config.bugfix_patch_bias).lower()}."
    )

    if config.policy_mode == "strict_semver":
        policy_actions.append("strict_semver kept model/deterministic classification unchanged.")
        return result, policy_effects, policy_actions

    policy_actions.append(
        "policy_mode recorded; boundary strictness is governed by unknown_boundary_policy."
    )
    if config.policy_mode == "manual_first":
        notes.append(
            "policy_mode=manual_first is active; unknown-boundary enforcement now uses unknown_boundary_policy."
        )
    return result, policy_effects, policy_actions


def manual_review_result(reasoning: str) -> dict[str, object]:
    return {
        "status": "manual_review",
        "label": None,
        "confidence": None,
        "reasoning": reasoning,
        "changelog": None,
    }


def apply_unknown_boundary_policy(
    result: dict[str, object],
    *,
    boundary_summary: dict[str, int],
    config: BumpkinConfig,
    notes: list[str],
) -> tuple[dict[str, object], list[str], list[str]]:
    effects: list[str] = []
    actions: list[str] = []
    status = str(result.get("status", "classified"))
    effects.append(f"unknown_boundary_policy={config.unknown_boundary_policy}.")
    if status != "classified":
        effects.append("unknown_boundary_policy configured; no effect (no classified label).")
        return result, effects, actions

    label = str(result.get("label", "")).upper()
    if label not in {"MINOR", "MAJOR"}:
        effects.append(
            f"unknown_boundary_policy configured; no effect (label={label or 'unknown'})."
        )
        return result, effects, actions

    unknown = int(boundary_summary.get("unknown", 0))
    public = int(boundary_summary.get("public", 0))
    if unknown <= 0 or public > 0:
        effects.append(
            "unknown_boundary_policy configured; no effect (boundary sufficiently known)."
        )
        return result, effects, actions

    updated = dict(result)
    if config.unknown_boundary_policy == "manual_review":
        actions.append("unknown_boundary_policy -> manual_review")
        effects.append(
            "unknown_boundary_policy applied: impactful unknown-boundary result requires manual review."
        )
        notes.append("Unknown boundary policy required manual review for impactful recommendation.")
        return (
            manual_review_result(
                "Public API boundary is unclear for an impactful recommendation. Manual review is required."
            ),
            effects,
            actions,
        )

    if config.unknown_boundary_policy == "patch_if_bugfix" and has_bugfix_intent(updated):
        actions.append("unknown_boundary_policy.patch_if_bugfix -> PATCH")
        effects.append(
            "unknown_boundary_policy applied: MINOR/MAJOR bugfix under unknown boundary remapped to PATCH."
        )
        updated["label"] = "PATCH"
        updated["confidence"] = "low"
        updated["changelog"] = "fix: internal bugfix under uncertain public-api boundary"
        updated["reasoning"] = (
            f"{updated.get('reasoning', '')} "
            "Unknown boundary policy remapped impactful bugfix recommendation to PATCH."
        ).strip()
        notes.append("Unknown boundary policy remapped impactful bugfix recommendation to PATCH.")
        return updated, effects, actions

    current_confidence = str(updated.get("confidence", "high")).lower()
    if current_confidence != "low":
        updated["confidence"] = "low"
        actions.append("unknown_boundary_policy -> confidence_low")
        effects.append(
            "unknown_boundary_policy applied: boundary uncertainty lowered confidence to low."
        )
        notes.append("Unknown boundary policy lowered confidence to low due to uncertain boundary.")
    else:
        effects.append("unknown_boundary_policy configured; no effect (confidence already low).")
    return updated, effects, actions


def detect_behavior_contract_signals(
    analyzed_files: list[str],
    *,
    policy: str,
) -> dict[str, object]:
    summary: dict[str, object] = {
        "policy": policy,
        "enabled": policy != "off",
        "total": 0,
        "categories": {"openapi": 0, "schema": 0, "route_contract": 0},
        "sample_files": [],
    }
    if policy == "off":
        return summary

    openapi_patterns = (
        "**/openapi.json",
        "**/openapi.yaml",
        "**/openapi.yml",
        "**/swagger.json",
        "**/swagger.yaml",
        "**/swagger.yml",
    )
    schema_patterns = (
        "**/schema/**",
        "**/schemas/**",
        "**/*.schema.json",
        "**/*.schema.ts",
        "**/*.schema.js",
        "**/*-schema.ts",
        "**/*-schema.js",
    )
    route_contract_pattern = re.compile(
        r"(^|/)(routes?|api)/.+(contract|response|dto|schema)", re.IGNORECASE
    )
    matched: dict[str, set[str]] = {"openapi": set(), "schema": set(), "route_contract": set()}
    for raw in analyzed_files:
        path = raw.strip().replace("\\", "/").lstrip("./")
        lower = path.lower()
        if not lower:
            continue
        if any(fnmatch.fnmatch(lower, pattern) for pattern in openapi_patterns):
            matched["openapi"].add(path)
        if any(fnmatch.fnmatch(lower, pattern) for pattern in schema_patterns):
            matched["schema"].add(path)
        if route_contract_pattern.search(lower):
            matched["route_contract"].add(path)

    categories = {name: len(values) for name, values in matched.items()}
    all_files = sorted({item for values in matched.values() for item in values})
    summary["categories"] = categories
    summary["total"] = len(all_files)
    summary["sample_files"] = all_files[:6]
    return summary


def summarize_evidence(
    findings: list[Finding],
    *,
    public_hints: list[str],
    contract_signals: dict[str, object],
) -> dict[str, int]:
    export_public = 0
    export_breaking = 0
    unknown_impactful = 0
    for finding in findings:
        severity = finding.severity.upper()
        if finding.rule == "python_requires_floor_raised":
            if severity in {"MINOR", "MAJOR"}:
                export_public += 1
            if severity == "MAJOR":
                export_breaking += 1
            continue
        boundary = classify_finding_boundary(finding, public_hints=public_hints)
        if severity in {"MINOR", "MAJOR"} and boundary == "unknown":
            unknown_impactful += 1
        if not finding.rule.startswith("export_"):
            continue
        if boundary == "internal":
            continue
        if severity in {"MINOR", "MAJOR"}:
            export_public += 1
        if severity == "MAJOR":
            export_breaking += 1

    contract_public = _to_int(contract_signals.get("total", 0), default=0)
    return {
        "export_public_evidence": export_public,
        "export_breaking_evidence": export_breaking,
        "behavior_contract_evidence": contract_public,
        "strong_public_evidence": export_public + contract_public,
        "strong_breaking_evidence": export_breaking,
        "unknown_impactful_findings": unknown_impactful,
    }


def apply_impact_evidence_threshold(
    result: dict[str, object],
    *,
    boundary_summary: dict[str, int],
    evidence_summary: dict[str, int],
    config: BumpkinConfig,
    notes: list[str],
) -> tuple[dict[str, object], list[str], list[str]]:
    effects: list[str] = []
    actions: list[str] = []
    mode = config.impact_evidence_threshold
    effects.append(f"impact_evidence_threshold={mode}.")
    status = str(result.get("status", "classified"))
    if status != "classified":
        effects.append("impact_evidence_threshold configured; no effect (no classified label).")
        return result, effects, actions

    label = str(result.get("label", "")).upper()
    if label not in {"MINOR", "MAJOR"}:
        effects.append(
            f"impact_evidence_threshold configured; no effect (label={label or 'unknown'})."
        )
        return result, effects, actions

    thresholds = {
        "lenient": {"minor_public": 1, "major_public": 1, "major_breaking": 1},
        "moderate": {"minor_public": 1, "major_public": 1, "major_breaking": 1},
        "strict": {"minor_public": 2, "major_public": 2, "major_breaking": 2},
    }[mode]

    public_evidence = int(evidence_summary.get("strong_public_evidence", 0))
    breaking_evidence = int(evidence_summary.get("strong_breaking_evidence", 0))
    unknown = int(boundary_summary.get("unknown", 0))
    public_boundary = int(boundary_summary.get("public", 0))
    ambiguous = unknown > 0 and public_boundary == 0
    updated = dict(result)

    if label == "MINOR" and public_evidence < thresholds["minor_public"]:
        if ambiguous:
            actions.append("impact_evidence_threshold.minor_unmet -> manual_review")
            effects.append(
                "impact_evidence_threshold applied: MINOR lacked public evidence under ambiguous boundary."
            )
            notes.append(
                "Impact evidence threshold required manual review: MINOR lacked minimum public evidence in ambiguous boundary."
            )
            return (
                manual_review_result(
                    "MINOR recommendation lacked minimum public-impact evidence under uncertain boundary."
                ),
                effects,
                actions,
            )
        updated["label"] = "PATCH"
        updated["confidence"] = "low"
        updated["reasoning"] = (
            f"{updated.get('reasoning', '')} "
            "Impact evidence threshold downgraded MINOR to PATCH due to insufficient public-impact evidence."
        ).strip()
        updated["changelog"] = "fix: update internal implementation"
        actions.append("impact_evidence_threshold.minor_unmet -> patch")
        effects.append("impact_evidence_threshold applied: MINOR downgraded to PATCH.")
        notes.append(
            "Impact evidence threshold downgraded MINOR to PATCH due to insufficient evidence."
        )
        return updated, effects, actions

    if label == "MAJOR":
        if public_evidence < thresholds["major_public"]:
            actions.append("impact_evidence_threshold.major_public_unmet -> manual_review")
            effects.append(
                "impact_evidence_threshold applied: MAJOR lacked minimum public-impact evidence."
            )
            notes.append(
                "Impact evidence threshold required manual review: MAJOR lacked minimum public-impact evidence."
            )
            return (
                manual_review_result("MAJOR recommendation lacked minimum public-impact evidence."),
                effects,
                actions,
            )
        if breaking_evidence < thresholds["major_breaking"]:
            updated["label"] = "MINOR"
            updated["confidence"] = "low"
            updated["reasoning"] = (
                f"{updated.get('reasoning', '')} "
                "Impact evidence threshold downgraded MAJOR to MINOR due to insufficient breaking-evidence count."
            ).strip()
            updated["changelog"] = "feat: add backward-compatible api changes"
            actions.append("impact_evidence_threshold.major_breaking_unmet -> minor")
            effects.append("impact_evidence_threshold applied: MAJOR downgraded to MINOR.")
            notes.append(
                "Impact evidence threshold downgraded MAJOR to MINOR due to insufficient breaking evidence."
            )
            return updated, effects, actions

    effects.append("impact_evidence_threshold configured; no effect (minimum evidence satisfied).")
    return updated, effects, actions


def apply_noise_suppression_policy(
    result: dict[str, object],
    *,
    noise_ratio: float,
    changed_files_total: int,
    evidence_summary: dict[str, int],
    config: BumpkinConfig,
    notes: list[str],
) -> tuple[dict[str, object], list[str], list[str]]:
    effects: list[str] = []
    actions: list[str] = []
    mode = config.noise_suppression_policy
    effects.append(f"noise_suppression_policy={mode}.")
    if mode == "off":
        effects.append("noise_suppression_policy=off; no effect.")
        return result, effects, actions

    status = str(result.get("status", "classified"))
    if status != "classified":
        effects.append("noise_suppression_policy configured; no effect (no classified label).")
        return result, effects, actions

    threshold_ratio, threshold_files = (0.65, 10) if mode == "balanced" else (0.45, 6)
    is_noisy = changed_files_total >= threshold_files and noise_ratio >= threshold_ratio
    if not is_noisy:
        effects.append(
            "noise_suppression_policy configured; no effect "
            f"(ratio={noise_ratio:.2f}, files={changed_files_total})."
        )
        return result, effects, actions

    updated = dict(result)
    label = str(updated.get("label", "")).upper()
    if label in {"MINOR", "MAJOR"} and str(updated.get("confidence", "")).lower() != "low":
        updated["confidence"] = "low"
        actions.append("noise_suppression_policy -> confidence_low")
        effects.append(
            "noise_suppression_policy applied: high non-actionable noise lowered confidence to low."
        )
    weak_public = int(evidence_summary.get("strong_public_evidence", 0)) == 0
    weak_breaking = int(evidence_summary.get("strong_breaking_evidence", 0)) == 0
    if label in {"MINOR", "MAJOR"} and (weak_public or (label == "MAJOR" and weak_breaking)):
        actions.append("noise_suppression_policy.weak_impactful_under_noise -> manual_review")
        effects.append(
            "noise_suppression_policy applied: high-noise impactful recommendation lacked strong evidence."
        )
        notes.append(
            "Noise suppression policy required manual review: high non-actionable noise with weak impactful evidence."
        )
        return (
            manual_review_result(
                "High non-actionable noise and weak impactful evidence make this recommendation unsafe."
            ),
            effects,
            actions,
        )

    notes.append(
        "Noise suppression policy lowered confidence due to high non-actionable noise ratio."
    )
    return updated, effects, actions


def apply_degraded_provider_policy(
    result: dict[str, object],
    *,
    mode_used: str,
    classification_source: str,
    config: BumpkinConfig,
    notes: list[str],
) -> tuple[dict[str, object], list[str], list[str]]:
    effects: list[str] = []
    actions: list[str] = []
    policy = config.degraded_provider_policy
    effects.append(f"degraded_provider_policy={policy}.")
    degraded = mode_used == "fallback-heuristic" or classification_source == "semantic-fallback"
    if not degraded:
        effects.append("degraded_provider_policy configured; no effect (authoritative source).")
        return result, effects, actions

    status = str(result.get("status", "classified"))
    label = str(result.get("label", "")).upper() if status == "classified" else None
    if policy == "MANUAL_REVIEW":
        if status != "manual_review":
            actions.append("degraded_provider_policy.manual_review -> manual_review")
            effects.append(
                "degraded_provider_policy applied: degraded provider path forced manual review."
            )
            notes.append(
                "Degraded provider policy forced manual review instead of accepting fallback classification."
            )
            return (
                manual_review_result(
                    "Model provider was degraded; policy requires manual review for reliability."
                ),
                effects,
                actions,
            )
        effects.append("degraded_provider_policy configured; no effect (already manual_review).")
        return result, effects, actions

    updated = dict(result)
    if status == "manual_review" or label in {"MAJOR", "MINOR", "NO_BUMP"}:
        updated["status"] = "classified"
        updated["label"] = "PATCH"
        updated["confidence"] = "low"
        updated["reasoning"] = (
            "Model provider was degraded; policy emitted conservative PATCH fallback."
        )
        updated["changelog"] = "fix: conservative patch bump due to degraded provider path"
        actions.append("degraded_provider_policy.patch -> PATCH")
        effects.append(
            "degraded_provider_policy applied: degraded provider path emitted conservative PATCH."
        )
        notes.append("Degraded provider policy emitted conservative PATCH fallback.")
        return updated, effects, actions

    effects.append("degraded_provider_policy configured; no effect (label already PATCH).")
    return updated, effects, actions
