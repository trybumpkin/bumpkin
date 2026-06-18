from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bumpkin.analysis.diffing import DiffResult
from bumpkin.analysis.findings import Finding
from bumpkin.orchestrator import finalize as orchestrator_finalize
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
    *,
    status: str,
    mode_used: str,
    prompt_metadata: PromptPackMetadata,
    model_used: str | None,
    analysis_state: str,
    classification_source: str,
    failure_category: str | None,
    fallback_reason: str | None,
    diff_result: DiffResult,
    result: dict[str, Any],
    findings: list[Finding],
    aggregation_trace: str | None,
    boundary_summary: dict[str, int],
    decision_trace: dict[str, Any],
    policy_effects: list[str],
    override_payload: dict[str, Any],
    impact_summary: dict[str, Any],
    evidence_summary: dict[str, int],
    behavior_contract_signals: dict[str, object],
    scope_mismatch_detected: bool,
    coverage_guard_triggered: bool,
    truncated_no_bump_guard_triggered: bool,
    surface_area_guard_triggered: bool,
    large_pr_guard_triggered: bool,
    scope_guard: dict[str, object],
    non_actionable_noise_ratio: float,
    chunking_meta: dict[str, object],
    planner_payload: dict[str, Any],
    coverage_contract: dict[str, object],
    evidence_items: list[dict[str, Any]],
    evidence_summary_meta: dict[str, Any],
    case_file: dict[str, Any],
    case_file_stats: dict[str, Any],
    court_advisory: dict[str, Any],
    decision_authority: str,
    deterministic_label: str | None,
    deterministic_next_tag: str | None,
    current_tag: str | None,
    next_tag: str | None,
    explainability_rows: list[dict[str, str]],
    semantic_facts: list[dict[str, Any]],
    proof_obligations: dict[str, Any],
    reasoning_trace: list[dict[str, Any]],
    contradictions: list[dict[str, Any]],
    notes: list[str],
    court_skipped_reason: str | None,
    court_fallback_reason: str | None,
    override_summary: str | None,
    override_status: str,
    court_model_used: str | None,
) -> CoreAnalysisResult:
    output = orchestrator_finalize.build_output_payload(
        status=status,
        mode_used=mode_used,
        prompt_metadata=prompt_metadata,
        model_used=model_used,
        analysis_state=analysis_state,
        classification_source=classification_source,
        failure_category=failure_category,
        fallback_reason=fallback_reason,
        diff_result=diff_result,
        result=result,
        findings=findings,
        aggregation_trace=aggregation_trace,
        boundary_summary=boundary_summary,
        decision_trace=decision_trace,
        policy_effects=policy_effects,
        override_payload=override_payload,
        impact_summary=impact_summary,
        evidence_summary=evidence_summary,
        behavior_contract_signals=behavior_contract_signals,
        scope_mismatch_detected=scope_mismatch_detected,
        coverage_guard_triggered=coverage_guard_triggered,
        truncated_no_bump_guard_triggered=truncated_no_bump_guard_triggered,
        surface_area_guard_triggered=surface_area_guard_triggered,
        large_pr_guard_triggered=large_pr_guard_triggered,
        scope_guard=scope_guard,
        non_actionable_noise_ratio=non_actionable_noise_ratio,
        chunking_meta=chunking_meta,
        planner_payload=planner_payload,
        coverage_contract=coverage_contract,
        evidence_items=evidence_items,
        evidence_summary_meta=evidence_summary_meta,
        case_file=case_file,
        case_file_stats=case_file_stats,
        advisory=court_advisory,
        decision_authority=decision_authority,
        deterministic_label=deterministic_label,
        deterministic_next_tag=deterministic_next_tag,
        current_tag=current_tag,
        next_tag=next_tag,
        explainability_rows=explainability_rows,
        semantic_facts=semantic_facts,
        proof_obligations=proof_obligations,
        reasoning_trace=reasoning_trace,
        contradictions=contradictions,
        notes=notes,
    )
    output["court_skipped_reason"] = court_skipped_reason
    output["court_fallback_reason"] = court_fallback_reason

    return CoreAnalysisResult(
        output=output,
        result=result,
        notes=notes,
        findings=findings,
        mode_used=mode_used,
        fallback_reason=fallback_reason,
        current_tag=current_tag,
        next_tag=next_tag,
        override_summary=override_summary,
        override_status=override_status,
        aggregation_trace=aggregation_trace,
        boundary_summary=boundary_summary,
        analysis_state=analysis_state,
        classification_source=classification_source,
        failure_category=failure_category,
        policy_effects=policy_effects,
        decision_trace=decision_trace,
        court_advisory=court_advisory,
        court_fallback_reason=court_fallback_reason,
        court_model_used=court_model_used,
        court_skipped_reason=court_skipped_reason,
        deterministic_label=deterministic_label,
        deterministic_next_tag=deterministic_next_tag,
        model_used=model_used,
        explainability_rows=explainability_rows,
        proof_obligations=proof_obligations,
        reasoning_trace=reasoning_trace,
        contradictions=contradictions,
    )
