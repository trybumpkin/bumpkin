from __future__ import annotations

from bumpkin.analysis.diffing import DiffResult
from bumpkin.config import BumpkinConfig
from bumpkin.orchestrator import court_authority as orchestrator_court_authority
from bumpkin.orchestrator import court_setup as orchestrator_court_setup
from bumpkin.orchestrator import postprocess as orchestrator_postprocess
from bumpkin.orchestrator.state import CorePipelineState
from bumpkin.planner import PlannerDecision


def _prepare_court_pipeline_state(
    *,
    semver_state: CorePipelineState,
    diff_result: DiffResult,
    token: str,
    mode: str,
    model: str,
    fallback_model: str | None,
    endpoint: str,
    max_retries: int,
    request_timeout: int,
    language_hints: list[str] | None,
    planner_decision: PlannerDecision,
    bumpkin_config: BumpkinConfig,
) -> CorePipelineState:
    base_classification = semver_state.base_classification
    local_notes = list(semver_state.local_notes)
    court_setup_artifacts = orchestrator_court_setup.prepare_court_setup(
        result=semver_state.result,
        findings=semver_state.findings,
        evidence_items=semver_state.evidence_items,
        policy_effects=semver_state.policy_effects,
        notes=local_notes,
        coverage_contract=semver_state.coverage_contract,
        boundary_summary=semver_state.boundary_summary,
        evidence_summary=semver_state.evidence_summary,
        allow_model_call=planner_decision.allow_model_call,
        token=token,
        mode=mode,
        model=model,
        fallback_model=fallback_model,
        endpoint=endpoint,
        max_retries=max_retries,
        request_timeout=request_timeout,
        language_hints=language_hints,
        classification_source=semver_state.classification_source,
        mode_used=base_classification.mode_used,
        next_tag=semver_state.next_tag,
    )
    semver_state.local_notes = court_setup_artifacts.notes
    semver_state.case_file = court_setup_artifacts.case_file
    semver_state.case_file_stats = court_setup_artifacts.case_file_stats
    semver_state.court_advisory = court_setup_artifacts.court_advisory
    semver_state.deterministic_label = court_setup_artifacts.deterministic_label
    semver_state.deterministic_confidence = court_setup_artifacts.deterministic_confidence
    semver_state.deterministic_next_tag = court_setup_artifacts.deterministic_next_tag
    semver_state.advisory_token = court_setup_artifacts.advisory_token
    semver_state.court_fallback_reason = court_setup_artifacts.court_fallback_reason
    semver_state.court_model_used = court_setup_artifacts.court_model_used
    semver_state.court_skipped_reason = court_setup_artifacts.court_skipped_reason
    semver_state.court_setup_artifacts = court_setup_artifacts
    return semver_state


def _apply_court_authority_and_postprocess_state(
    *,
    court_state: CorePipelineState,
    diff_result: DiffResult,
    endpoint: str,
    model: str,
    max_retries: int,
    request_timeout: int,
    bumpkin_config: BumpkinConfig,
) -> CorePipelineState:
    court_setup_artifacts = court_state.court_setup_artifacts
    if court_setup_artifacts is None:
        raise RuntimeError("Court setup state is required before authority processing.")
    base_result = court_state.result
    base_status = court_state.status
    base_classification_source = court_state.classification_source
    base_analysis_state = court_state.analysis_state
    base_failure_category = court_state.failure_category
    authority_artifacts = orchestrator_court_authority.apply_court_authority(
        decision_authority=bumpkin_config.decision_authority_mode,
        court_advisory=court_setup_artifacts.court_advisory,
        case_file=court_setup_artifacts.case_file,
        pre_court_result=court_setup_artifacts.pre_court_result,
        pre_court_status=court_setup_artifacts.pre_court_status,
        deterministic_label=court_setup_artifacts.deterministic_label,
        deterministic_next_tag=court_setup_artifacts.deterministic_next_tag,
        court_fallback_reason=court_setup_artifacts.court_fallback_reason,
        court_model_used=court_setup_artifacts.court_model_used,
        advisory_token=court_setup_artifacts.advisory_token,
        endpoint=endpoint,
        model=model,
        max_retries=max_retries,
        request_timeout=request_timeout,
        diff_result=diff_result,
        pre_1_0_breaking_as_minor=bumpkin_config.pre_1_0_breaking_as_minor,
        result=base_result,
        status=base_status,
        classification_source=base_classification_source,
        analysis_state=base_analysis_state,
        failure_category=base_failure_category,
        current_tag=court_state.current_tag,
        next_tag=court_state.next_tag,
        notes=list(court_state.local_notes),
    )
    decision_trace = dict(court_state.decision_trace)
    decision_trace["decision_authority"] = bumpkin_config.decision_authority_mode
    decision_trace["deterministic_label"] = court_state.deterministic_label
    decision_trace["deterministic_next_tag"] = court_state.deterministic_next_tag
    semantic_trace_artifacts = orchestrator_postprocess.build_semantic_trace_artifacts(
        result=authority_artifacts.result,
        status=authority_artifacts.status,
        court_advisory=court_setup_artifacts.court_advisory,
        case_file=court_setup_artifacts.case_file,
        diff_result=diff_result,
        event_labels=[],
        policy_effects=list(court_state.policy_effects),
        decision_trace=decision_trace,
        classification_source=authority_artifacts.classification_source,
        analysis_state=authority_artifacts.analysis_state,
        failure_category=authority_artifacts.failure_category,
        next_tag=authority_artifacts.next_tag,
        notes=authority_artifacts.notes,
        deterministic_label=court_setup_artifacts.deterministic_label,
        court_skipped_reason=court_setup_artifacts.court_skipped_reason,
    )
    court_state.result = semantic_trace_artifacts.result
    court_state.status = semantic_trace_artifacts.status
    court_state.classification_source = semantic_trace_artifacts.classification_source
    court_state.analysis_state = semantic_trace_artifacts.analysis_state
    court_state.failure_category = semantic_trace_artifacts.failure_category
    court_state.next_tag = semantic_trace_artifacts.next_tag
    court_state.local_notes = semantic_trace_artifacts.notes
    court_state.decision_trace = semantic_trace_artifacts.decision_trace
    court_state.explainability_rows = semantic_trace_artifacts.explainability_rows
    court_state.semantic_facts = semantic_trace_artifacts.semantic_facts
    court_state.proof_obligations = semantic_trace_artifacts.proof_obligations
    court_state.reasoning_trace = semantic_trace_artifacts.reasoning_trace
    court_state.contradictions = semantic_trace_artifacts.contradictions
    court_state.decision_authority = bumpkin_config.decision_authority_mode
    court_state.current_tag = authority_artifacts.current_tag
    court_state.court_model_used = court_setup_artifacts.court_model_used
    return court_state
