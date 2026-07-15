from __future__ import annotations

from typing import Any

from bumpkin.config import BumpkinConfig
from bumpkin.policies.policy_basics import has_bugfix_intent, manual_review_result


def apply_unknown_boundary_policy(
    result: dict[str, object],
    *,
    boundary_summary: dict[str, int],
    config: BumpkinConfig,
    notes: list[str],
) -> tuple[dict[str, object], list[str], list[str]]:
    effects = [f"unknown_boundary_policy={config.unknown_boundary_policy}."]
    actions: list[str] = []
    if str(result.get("status", "classified")) != "classified":
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
    updated: dict[str, Any] = dict(result)
    if config.unknown_boundary_policy == "patch_if_bugfix" and has_bugfix_intent(updated):
        actions.append("unknown_boundary_policy.patch_if_bugfix -> PATCH")
        effects.append(
            "unknown_boundary_policy applied: MINOR/MAJOR bugfix under unknown boundary remapped to PATCH."
        )
        updated.update(
            {
                "label": "PATCH",
                "confidence": "low",
                "changelog": "fix: internal bugfix under uncertain public-api boundary",
            }
        )
        updated["reasoning"] = (
            f"{updated.get('reasoning', '')} Unknown boundary policy remapped impactful bugfix recommendation to PATCH.".strip()
        )
        notes.append("Unknown boundary policy remapped impactful bugfix recommendation to PATCH.")
        return updated, effects, actions
    if str(updated.get("confidence", "high")).lower() != "low":
        updated["confidence"] = "low"
        actions.append("unknown_boundary_policy -> confidence_low")
        effects.append(
            "unknown_boundary_policy applied: boundary uncertainty lowered confidence to low."
        )
        notes.append("Unknown boundary policy lowered confidence to low due to uncertain boundary.")
    else:
        effects.append("unknown_boundary_policy configured; no effect (confidence already low).")
    return updated, effects, actions
