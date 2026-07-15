from __future__ import annotations

from bumpkin.config import BumpkinConfig
from bumpkin.policies.policy_basics import manual_review_result


def apply_impact_evidence_threshold(
    result: dict[str, object],
    *,
    boundary_summary: dict[str, int],
    evidence_summary: dict[str, int],
    config: BumpkinConfig,
    notes: list[str],
) -> tuple[dict[str, object], list[str], list[str]]:
    effects = [f"impact_evidence_threshold={config.impact_evidence_threshold}."]
    actions: list[str] = []
    if str(result.get("status", "classified")) != "classified":
        effects.append("impact_evidence_threshold configured; no effect (no classified label).")
        return result, effects, actions
    label = str(result.get("label", "")).upper()
    if label not in {"MINOR", "MAJOR"}:
        effects.append(
            f"impact_evidence_threshold configured; no effect (label={label or 'unknown'})."
        )
        return result, effects, actions
    threshold = 2 if config.impact_evidence_threshold == "strict" else 1
    public_evidence = int(evidence_summary.get("strong_public_evidence", 0))
    breaking_evidence = int(evidence_summary.get("strong_breaking_evidence", 0))
    ambiguous = (
        int(boundary_summary.get("unknown", 0)) > 0 and int(boundary_summary.get("public", 0)) == 0
    )
    if label == "MINOR" and public_evidence < threshold:
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
        updated = dict(
            result, label="PATCH", confidence="low", changelog="fix: update internal implementation"
        )
        updated["reasoning"] = (
            f"{updated.get('reasoning', '')} Impact evidence threshold downgraded MINOR to PATCH due to insufficient public-impact evidence.".strip()
        )
        actions.append("impact_evidence_threshold.minor_unmet -> patch")
        effects.append("impact_evidence_threshold applied: MINOR downgraded to PATCH.")
        notes.append(
            "Impact evidence threshold downgraded MINOR to PATCH due to insufficient evidence."
        )
        return updated, effects, actions
    if label == "MAJOR" and public_evidence < threshold:
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
    if label == "MAJOR" and breaking_evidence < threshold:
        updated = dict(
            result,
            label="MINOR",
            confidence="low",
            changelog="feat: add backward-compatible api changes",
        )
        updated["reasoning"] = (
            f"{updated.get('reasoning', '')} Impact evidence threshold downgraded MAJOR to MINOR due to insufficient breaking-evidence count.".strip()
        )
        actions.append("impact_evidence_threshold.major_breaking_unmet -> minor")
        effects.append("impact_evidence_threshold applied: MAJOR downgraded to MINOR.")
        notes.append(
            "Impact evidence threshold downgraded MAJOR to MINOR due to insufficient breaking evidence."
        )
        return updated, effects, actions
    effects.append("impact_evidence_threshold configured; no effect (minimum evidence satisfied).")
    return dict(result), effects, actions
