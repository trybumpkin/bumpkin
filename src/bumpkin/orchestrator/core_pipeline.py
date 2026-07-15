from __future__ import annotations

from bumpkin.analysis.diffing import DiffResult
from bumpkin.config import BumpkinConfig
from bumpkin.orchestrator.core_assembly import (
    CoreAnalysisResult,
    _assemble_core_analysis_result_from_state,
)
from bumpkin.orchestrator.core_court import (
    _apply_court_authority_and_postprocess_state,
    _prepare_court_pipeline_state,
)
from bumpkin.orchestrator.core_semver import (
    _finalize_semver_analysis_state,
    _prepare_semver_analysis_state,
)
from bumpkin.planner import PlannerDecision
from bumpkin.prompt_pack import PromptPackMetadata


def analyze_diff_core(
    *,
    diff_result: DiffResult,
    mode: str,
    model: str,
    fallback_model: str | None,
    endpoint: str,
    token: str,
    max_retries: int,
    request_timeout: int,
    prompt_metadata: PromptPackMetadata,
    bumpkin_config: BumpkinConfig,
    planner_decision: PlannerDecision,
    notes: list[str] | None = None,
    event_labels: list[str] | None = None,
    scope_mismatch_detected: bool = False,
    scope_mismatch_reason: str | None = None,
    scope_guard: dict[str, object] | None = None,
    public_api_hints: list[str] | None = None,
    language_hints: list[str] | None = None,
) -> CoreAnalysisResult:
    semver_state = _prepare_semver_analysis_state(
        diff_result=diff_result,
        mode=mode,
        bumpkin_config=bumpkin_config,
        scope_mismatch_detected=scope_mismatch_detected,
        scope_mismatch_reason=scope_mismatch_reason,
        scope_guard=scope_guard,
        public_api_hints=public_api_hints,
        notes=notes,
    )
    semver_state = _finalize_semver_analysis_state(
        semver_state=semver_state,
        planner_decision=planner_decision,
        prompt_metadata=prompt_metadata,
        diff_result=diff_result,
        bumpkin_config=bumpkin_config,
        event_labels=list(event_labels or []),
    )
    court_state = _prepare_court_pipeline_state(
        semver_state=semver_state,
        diff_result=diff_result,
        token=token,
        mode=mode,
        model=model,
        fallback_model=fallback_model,
        endpoint=endpoint,
        max_retries=max_retries,
        request_timeout=request_timeout,
        language_hints=language_hints,
        planner_decision=planner_decision,
        bumpkin_config=bumpkin_config,
    )
    court_state = _apply_court_authority_and_postprocess_state(
        court_state=court_state,
        diff_result=diff_result,
        endpoint=endpoint,
        model=model,
        max_retries=max_retries,
        request_timeout=request_timeout,
        bumpkin_config=bumpkin_config,
    )
    return _assemble_core_analysis_result_from_state(court_state, prompt_metadata)
