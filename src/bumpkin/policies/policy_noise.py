from __future__ import annotations

from bumpkin.config import BumpkinConfig
from bumpkin.policies.policy_basics import manual_review_result


def apply_noise_suppression_policy(
    result: dict[str, object],
    *,
    noise_ratio: float,
    changed_files_total: int,
    evidence_summary: dict[str, int],
    config: BumpkinConfig,
    notes: list[str],
) -> tuple[dict[str, object], list[str], list[str]]:
    effects = [f"noise_suppression_policy={config.noise_suppression_policy}."]
    actions: list[str] = []
    mode = config.noise_suppression_policy
    if mode == "off":
        effects.append("noise_suppression_policy=off; no effect.")
        return result, effects, actions
    if str(result.get("status", "classified")) != "classified":
        effects.append("noise_suppression_policy configured; no effect (no classified label).")
        return result, effects, actions
    threshold_ratio, threshold_files = (0.65, 10) if mode == "balanced" else (0.45, 6)
    if changed_files_total < threshold_files or noise_ratio < threshold_ratio:
        effects.append(
            f"noise_suppression_policy configured; no effect (ratio={noise_ratio:.2f}, files={changed_files_total})."
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
