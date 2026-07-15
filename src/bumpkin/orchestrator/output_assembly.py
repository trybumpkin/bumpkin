from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bumpkin.analysis.findings import Finding
from bumpkin.orchestrator import finalize as orchestrator_finalize
from bumpkin.orchestrator.state import CorePipelineState
from bumpkin.prompt_pack import PromptPackMetadata


@dataclass(frozen=True)
class CoreAnalysisResult:
    output: dict[str, Any]
    result: dict[str, Any]
    notes: list[str]
    findings: list[Finding]
    mode_used: str
    fallback_reason: str | None
    current_tag: str | None
    next_tag: str | None
    override_summary: str | None
    override_status: str
    aggregation_trace: str | None
    boundary_summary: dict[str, int]
    analysis_state: str
    classification_source: str
    failure_category: str | None
    policy_effects: list[str]
    decision_trace: dict[str, Any]
    court_advisory: dict[str, Any]
    court_fallback_reason: str | None
    court_model_used: str | None
    court_skipped_reason: str | None
    deterministic_label: str | None
    deterministic_next_tag: str | None
    model_used: str | None
    explainability_rows: list[dict[str, str]]
    proof_obligations: dict[str, Any]
    reasoning_trace: list[dict[str, Any]]
    contradictions: list[dict[str, Any]]


def assemble_core_analysis_result(
    *, state: CorePipelineState, prompt_metadata: PromptPackMetadata
) -> CoreAnalysisResult:
    output = _build_output_payload(state=state, prompt_metadata=prompt_metadata)
    output["court_skipped_reason"] = state.court_skipped_reason
    output["court_fallback_reason"] = state.court_fallback_reason
    return _build_result(state=state, output=output)


def _build_output_payload(
    *, state: CorePipelineState, prompt_metadata: PromptPackMetadata
) -> dict[str, Any]:
    return orchestrator_finalize.build_output_payload(
        status=state.status,
        mode_used=state.mode_used,
        prompt_metadata=prompt_metadata,
        model_used=state.model_used,
        analysis_state=state.analysis_state,
        classification_source=state.classification_source,
        failure_category=state.failure_category,
        fallback_reason=state.fallback_reason,
        diff_result=state.diff_result,
        result=state.result,
        findings=state.findings,
        aggregation_trace=state.aggregation_trace,
        boundary_summary=state.boundary_summary,
        decision_trace=state.decision_trace,
        policy_effects=state.policy_effects,
        override_payload=state.override_payload,
        impact_summary=state.impact_summary,
        evidence_summary=state.evidence_summary,
        behavior_contract_signals=state.behavior_contract_signals,
        scope_mismatch_detected=state.scope_mismatch_detected,
        coverage_guard_triggered=state.coverage_guard_triggered,
        truncated_no_bump_guard_triggered=state.truncated_no_bump_guard_triggered,
        surface_area_guard_triggered=state.surface_area_guard_triggered,
        large_pr_guard_triggered=state.large_pr_guard_triggered,
        scope_guard=state.local_scope_guard,
        non_actionable_noise_ratio=state.non_actionable_noise_ratio,
        chunking_meta=state.chunking_meta,
        planner_payload=state.planner_payload,
        coverage_contract=state.coverage_contract,
        evidence_items=[item.to_dict() for item in state.evidence_items],
        evidence_summary_meta=state.evidence_summary_meta,
        case_file=state.case_file,
        case_file_stats=state.case_file_stats,
        advisory=state.court_advisory,
        decision_authority=state.decision_authority,
        deterministic_label=state.deterministic_label,
        deterministic_next_tag=state.deterministic_next_tag,
        current_tag=state.current_tag,
        next_tag=state.next_tag,
        explainability_rows=state.explainability_rows,
        semantic_facts=state.semantic_facts,
        proof_obligations=state.proof_obligations,
        reasoning_trace=state.reasoning_trace,
        contradictions=state.contradictions,
        notes=state.local_notes,
    )


def _build_result(*, state: CorePipelineState, output: dict[str, Any]) -> CoreAnalysisResult:
    return CoreAnalysisResult(
        output=output,
        result=state.result,
        notes=state.local_notes,
        findings=state.findings,
        mode_used=state.mode_used,
        fallback_reason=state.fallback_reason,
        current_tag=state.current_tag,
        next_tag=state.next_tag,
        override_summary=state.override_summary,
        override_status=state.override_status,
        aggregation_trace=state.aggregation_trace,
        boundary_summary=state.boundary_summary,
        analysis_state=state.analysis_state,
        classification_source=state.classification_source,
        failure_category=state.failure_category,
        policy_effects=state.policy_effects,
        decision_trace=state.decision_trace,
        court_advisory=state.court_advisory,
        court_fallback_reason=state.court_fallback_reason,
        court_model_used=state.court_model_used,
        court_skipped_reason=state.court_skipped_reason,
        deterministic_label=state.deterministic_label,
        deterministic_next_tag=state.deterministic_next_tag,
        model_used=state.model_used,
        explainability_rows=state.explainability_rows,
        proof_obligations=state.proof_obligations,
        reasoning_trace=state.reasoning_trace,
        contradictions=state.contradictions,
    )
