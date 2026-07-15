from __future__ import annotations

from bumpkin.config import BumpkinConfig
from bumpkin.policies.policy_basics import manual_review_result


def apply_degraded_provider_policy(
    result: dict[str, object],
    *,
    mode_used: str,
    classification_source: str,
    config: BumpkinConfig,
    notes: list[str],
) -> tuple[dict[str, object], list[str], list[str]]:
    effects = [f"degraded_provider_policy={config.degraded_provider_policy}."]
    actions: list[str] = []
    degraded = mode_used == "fallback-heuristic" or classification_source == "semantic-fallback"
    if not degraded:
        effects.append("degraded_provider_policy configured; no effect (authoritative source).")
        return result, effects, actions
    status = str(result.get("status", "classified"))
    label = str(result.get("label", "")).upper() if status == "classified" else None
    if config.degraded_provider_policy == "MANUAL_REVIEW":
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
    if status == "manual_review" or label in {"MAJOR", "MINOR", "NO_BUMP"}:
        updated = dict(
            result,
            status="classified",
            label="PATCH",
            confidence="low",
            reasoning="Model provider was degraded; policy emitted conservative PATCH fallback.",
            changelog="fix: conservative patch bump due to degraded provider path",
        )
        actions.append("degraded_provider_policy.patch -> PATCH")
        effects.append(
            "degraded_provider_policy applied: degraded provider path emitted conservative PATCH."
        )
        notes.append("Degraded provider policy emitted conservative PATCH fallback.")
        return updated, effects, actions
    effects.append("degraded_provider_policy configured; no effect (label already PATCH).")
    return dict(result), effects, actions
