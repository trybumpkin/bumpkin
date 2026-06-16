from __future__ import annotations

from typing import Any

from bumpkin.orchestrator import explainability as orchestrator_explainability


def _semantic_severity_rank(label: str) -> int:
    ordering = {"MAJOR": 4, "MINOR": 3, "PATCH": 2, "NO_BUMP": 1}
    return ordering.get(label.upper(), 0)


def _extract_contradiction_paths(contradictions: list[dict[str, Any]]) -> set[str]:
    paths: set[str] = set()
    for item in contradictions:
        raw_paths = orchestrator_explainability._as_object_list(item.get("evidence_paths", []))
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
        raw_paths = orchestrator_explainability._as_object_list(
            contradiction.get("evidence_paths", [])
        )
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


semantic_severity_rank = _semantic_severity_rank
extract_contradiction_paths = _extract_contradiction_paths
prioritize_semantic_facts = _prioritize_semantic_facts
normalize_policy_id = _normalize_policy_id
build_reasoning_trace = _build_reasoning_trace
detect_contradictions = _detect_contradictions
