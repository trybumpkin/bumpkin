from __future__ import annotations

from bumpkin.planner import PlannerDecision
from bumpkin.prompt_pack import PromptPackMetadata


def append_semver_notes(
    *,
    notes: list[str],
    mode_used: str,
    planner_decision: PlannerDecision,
    status: str,
    analysis_state: str,
    classification_source: str,
    failure_category: str | None,
    prompt_metadata: PromptPackMetadata,
) -> list[str]:
    local_notes = list(notes)
    mode_note = {
        "deterministic-findings": "Deterministic findings selected the base SemVer classification.",
        "deterministic-heuristic": "Deterministic semantic heuristic selected the base SemVer classification.",
        "deterministic-no-diff": "No diff content detected; deterministic NO_BUMP classification applied.",
        "scope-guard": "Scope mismatch guard blocked automated classification; manual review required.",
        "stub": "Stub mode selected for deterministic base classification.",
    }.get(mode_used)
    if mode_note:
        local_notes.append(mode_note)
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
    return local_notes
