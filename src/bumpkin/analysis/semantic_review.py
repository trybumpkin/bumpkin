from __future__ import annotations

from typing import Any, cast


def _as_object_list(value: object) -> list[object] | None:
    if not isinstance(value, list):
        return None
    return cast("list[object]", value)


def row_has_semantic_transition(row: dict[str, str]) -> bool:
    before = str(row.get("before", "")).strip()
    after = str(row.get("after", "")).strip()
    if before and after:
        return True
    action = str(row.get("action", "")).strip().lower()
    return action in {"added", "removed", "renamed", "tightened", "unchanged"}


def row_satisfies_patch_transition(row: dict[str, str]) -> bool:
    impact_scope = str(row.get("impact_scope", "")).strip().lower()
    suggested_bump = str(row.get("suggested_bump", "")).strip().upper()
    if impact_scope != "runtime_internal" or suggested_bump != "PATCH":
        return False
    return row_has_semantic_transition(row)


def evaluate_proof_obligations(
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
        row_has_semantic_transition(item) for item in semantic_facts
    )
    patch_transition = (
        any(row_satisfies_patch_transition(item) for item in semantic_facts)
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


def critical_missing_proof_obligations(proof_obligations: dict[str, Any]) -> list[str]:
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


def semantic_severity_rank(label: str) -> int:
    ordering = {"MAJOR": 4, "MINOR": 3, "PATCH": 2, "NO_BUMP": 1}
    return ordering.get(label.upper(), 0)


def extract_contradiction_paths(contradictions: list[dict[str, Any]]) -> set[str]:
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


def prioritize_semantic_facts(
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
        return (bucket, -semantic_severity_rank(suggested), path, rule, target)

    ranked = sorted(semantic_facts, key=_priority)
    return ranked[:max_items]


def normalize_policy_id(effect: str) -> str:
    normalized = str(effect).strip().lower()
    if not normalized:
        return "policy.unknown"
    token = normalized.split(";", 1)[0].split(" ", 1)[0]
    compact = "".join(ch for ch in token if ch.isalnum() or ch in {"_", "-", ".", ":"})
    return compact or "policy.unknown"


def build_reasoning_trace(
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
                    "id": normalize_policy_id(normalized_effect),
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


def detect_contradictions(
    *,
    event_labels: list[str],
    semantic_facts: list[dict[str, str]],
    status: str,
    final_label: str | None,
) -> list[dict[str, Any]]:
    fix_intent, no_bump_intent = _event_intent_flags(event_labels)
    runtime_rows = _runtime_semantic_rows(semantic_facts)
    public_change_rows = _public_change_rows(semantic_facts)
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
                "evidence_paths": _semantic_paths(public_change_rows),
            }
        )

    if no_bump_intent and runtime_rows:
        contradictions.append(
            {
                "code": "intent_no_bump_vs_runtime_delta",
                "message": "PR intent indicates NO_BUMP, but runtime semantic deltas were detected.",
                "severity": "high",
                "evidence_paths": _semantic_paths(runtime_rows),
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
                "evidence_paths": _semantic_paths(runtime_rows),
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


def _event_intent_flags(event_labels: list[str]) -> tuple[bool, bool]:
    labels = {str(label).strip().lower() for label in event_labels if str(label).strip()}
    fix_intent = any(token in label for label in labels for token in ("bump:patch", "fix", "bug"))
    no_bump_intent = bool(
        labels & {"bump:no-bump", "bump:no_bump", "no-bump", "no_bump", "release:none"}
    )
    return fix_intent, no_bump_intent


def _runtime_semantic_rows(semantic_facts: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        row
        for row in semantic_facts
        if str(row.get("impact_scope", "")).strip().lower() != "non_runtime"
        and str(row.get("action", "")).strip().lower() != "unchanged"
    ]


def _public_change_rows(semantic_facts: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        row
        for row in semantic_facts
        if str(row.get("impact_scope", "")).strip().lower() == "public_api"
        and str(row.get("suggested_bump", "")).strip().upper() in {"MAJOR", "MINOR"}
    ]


def _semantic_paths(rows: list[dict[str, str]]) -> list[str]:
    return sorted(
        {str(item.get("path", "")).strip() for item in rows if str(item.get("path", "")).strip()}
    )


__all__ = [
    "build_reasoning_trace",
    "critical_missing_proof_obligations",
    "detect_contradictions",
    "evaluate_proof_obligations",
    "extract_contradiction_paths",
    "normalize_policy_id",
    "prioritize_semantic_facts",
    "row_has_semantic_transition",
    "row_satisfies_patch_transition",
    "semantic_severity_rank",
]
