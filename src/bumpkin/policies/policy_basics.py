from __future__ import annotations

from bumpkin.config import BumpkinConfig


def derive_docs_only_policy_effect(*, status: str, label: str | None, docs_only_label: str) -> str:
    normalized_label = str(label or "").upper()
    if docs_only_label == "NO_BUMP":
        return "docs_only_label=NO_BUMP (default)."
    if status != "classified":
        return "docs_only_label=PATCH configured; no remap applied (no base recommendation)."
    if normalized_label == "NO_BUMP":
        return "docs_only_label=PATCH applied: remapped NO_BUMP -> PATCH."
    return f"docs_only_label=PATCH configured; no remap applied (base label={normalized_label or 'unknown'})."


def derive_pre_1_0_policy_effect(
    *, status: str, label: str | None, current_tag: str | None, pre_1_0_breaking_as_minor: bool
) -> str | None:
    from bumpkin.versioning.tags import parse_tag

    setting = str(pre_1_0_breaking_as_minor).lower()
    if status != "classified":
        return (
            f"pre_1_0_breaking_as_minor={setting} configured; no effect (no authoritative label)."
        )
    normalized_label = str(label or "").upper()
    if normalized_label != "MAJOR":
        return f"pre_1_0_breaking_as_minor={setting} configured; no effect (label={normalized_label or 'unknown'})."
    parsed = parse_tag(current_tag or "") if current_tag else None
    if not parsed or parsed.scheme != "zero-based":
        return f"pre_1_0_breaking_as_minor={setting} configured; no effect (tag scheme is not zero-based)."
    if pre_1_0_breaking_as_minor:
        return "pre_1_0_breaking_as_minor=true applied: MAJOR treated as minor bump before 1.0.0."
    return "pre_1_0_breaking_as_minor=false applied: MAJOR used strict 1.0.0 semantics."


def has_bugfix_intent(result: dict[str, object]) -> bool:
    changelog = str(result.get("changelog") or "").strip().lower()
    if changelog.startswith("fix:"):
        return True
    reasoning = str(result.get("reasoning") or "").strip().lower()
    return any(
        token in reasoning
        for token in ("bug fix", "bugfix", "fix", "regression", "internal", "refactor", "hotfix")
    )


def manual_review_result(reasoning: str) -> dict[str, object]:
    return {
        "status": "manual_review",
        "label": None,
        "confidence": None,
        "reasoning": reasoning,
        "changelog": None,
    }


def apply_policy_mode(
    result: dict[str, object],
    *,
    boundary_summary: dict[str, int],
    config: BumpkinConfig,
    notes: list[str],
) -> tuple[dict[str, object], list[str], list[str]]:
    del boundary_summary
    effects = [
        f"policy_mode={config.policy_mode} configured; no effect (status={result.get('status', 'classified')})."
    ]
    actions: list[str] = []
    if str(result.get("status", "classified")) != "classified":
        return result, effects, actions
    effects = [
        f"policy_mode={config.policy_mode}; bugfix_patch_bias={str(config.bugfix_patch_bias).lower()}. "
    ]
    effects[0] = effects[0].rstrip()
    if config.policy_mode == "strict_semver":
        return result, effects, ["strict_semver kept model/deterministic classification unchanged."]
    actions.append(
        "policy_mode recorded; boundary strictness is governed by unknown_boundary_policy."
    )
    if config.policy_mode == "manual_first":
        notes.append(
            "policy_mode=manual_first is active; unknown-boundary enforcement now uses unknown_boundary_policy."
        )
    return result, effects, actions
