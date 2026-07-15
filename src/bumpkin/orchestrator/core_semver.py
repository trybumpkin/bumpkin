from __future__ import annotations

from bumpkin.analysis.diffing import DiffResult
from bumpkin.analysis.evidence import build_evidence_items, summarize_evidence_items
from bumpkin.analysis.findings import build_filesystem_workspace_loader, detect_semver_findings
from bumpkin.analysis.impact import summarize_impact
from bumpkin.config import BumpkinConfig
from bumpkin.orchestrator import analysis_stage as orchestrator_analysis_stage
from bumpkin.orchestrator import base_classification as orchestrator_base_classification
from bumpkin.orchestrator import finalize as orchestrator_finalize
from bumpkin.orchestrator import semver_notes
from bumpkin.orchestrator.state import CorePipelineState
from bumpkin.planner import PlannerDecision
from bumpkin.policies import engine as policy_engine
from bumpkin.prompt_pack import PromptPackMetadata


def _workspace_loader_for_diff_result(diff_result: DiffResult):
    repo_root = (diff_result.repo_root or "").strip()
    if not repo_root:
        return None
    return build_filesystem_workspace_loader(repo_root)


def _prepare_semver_analysis_state(
    *,
    diff_result: DiffResult,
    mode: str,
    bumpkin_config: BumpkinConfig,
    scope_mismatch_detected: bool,
    scope_mismatch_reason: str | None,
    scope_guard: dict[str, object] | None,
    public_api_hints: list[str] | None,
    notes: list[str] | None,
) -> CorePipelineState:
    local_notes = list(notes or [])
    local_public_hints = policy_engine.dedupe_preserving_order(list(public_api_hints or []))
    behavior_contract_signals = policy_engine.detect_behavior_contract_signals(
        diff_result.analyzed_files,
        policy=bumpkin_config.behavior_contract_policy,
    )
    workspace_loader = _workspace_loader_for_diff_result(diff_result)
    findings = (
        detect_semver_findings(
            diff_result.full_diff_text,
            workspace_loader=workspace_loader,
        )
        if diff_result.full_diff_text and not scope_mismatch_detected
        else []
    )
    evidence_items = build_evidence_items(
        findings=findings,
        diff_text=diff_result.full_diff_text,
        behavior_contract_signals=behavior_contract_signals,
    )
    evidence_summary_meta = summarize_evidence_items(evidence_items)
    if evidence_items:
        local_notes.append(f"Evidence extraction produced {len(evidence_items)} item(s).")

    chunking_meta: dict[str, object] = {
        "enabled": bool(bumpkin_config.chunking_enabled),
        "chunk_count": 0,
        "succeeded": 0,
        "failed": 0,
        "skipped": 0,
        "max_chunk_tokens": bumpkin_config.chunk_max_tokens,
        "max_chunk_count": bumpkin_config.chunk_max_count,
        "failure_policy": bumpkin_config.chunk_failure_policy,
        "files_total": len(diff_result.analyzed_files),
        "files_covered": len(diff_result.analyzed_files),
        "files_omitted": 0,
        "omitted_files": [],
        "omitted_files_sample": [],
    }
    base_classification = orchestrator_base_classification.determine_base_classification(
        diff_result=diff_result,
        findings=findings,
        mode=mode,
        scope_mismatch_detected=scope_mismatch_detected,
        scope_mismatch_reason=scope_mismatch_reason,
        surface_area_hints=local_public_hints,
        notes=local_notes,
    )
    analysis_stage = orchestrator_analysis_stage.apply_analysis_stage(
        result=base_classification.result,
        findings=findings,
        behavior_contract_signals=behavior_contract_signals,
        diff_result=diff_result,
        bumpkin_config=bumpkin_config,
        local_public_hints=local_public_hints,
        chunking_meta=chunking_meta,
        mode_used=base_classification.mode_used,
        fallback_reason=base_classification.fallback_reason,
        scope_mismatch_detected=scope_mismatch_detected,
        notes=base_classification.notes,
    )
    return CorePipelineState(
        diff_result=diff_result,
        behavior_contract_signals=behavior_contract_signals,
        findings=findings,
        evidence_items=evidence_items,
        evidence_summary_meta=evidence_summary_meta,
        chunking_meta=chunking_meta,
        base_classification=base_classification,
        analysis_stage=analysis_stage,
        local_notes=analysis_stage.notes,
        local_public_hints=local_public_hints,
        scope_mismatch_detected=scope_mismatch_detected,
        local_scope_guard=dict(scope_guard or {}),
        result=analysis_stage.result,
    )


def _finalize_semver_analysis_state(
    *,
    semver_state: CorePipelineState,
    planner_decision: PlannerDecision,
    prompt_metadata: PromptPackMetadata,
    diff_result: DiffResult,
    bumpkin_config: BumpkinConfig,
    event_labels: list[str],
) -> CorePipelineState:
    base_classification = semver_state.base_classification
    analysis_stage = semver_state.analysis_stage
    local_notes = semver_notes.append_semver_notes(
        notes=list(semver_state.local_notes),
        mode_used=base_classification.mode_used,
        planner_decision=planner_decision,
        status=analysis_stage.status,
        analysis_state=analysis_stage.analysis_state,
        classification_source=analysis_stage.classification_source,
        failure_category=analysis_stage.failure_category,
        prompt_metadata=prompt_metadata,
    )
    findings = semver_state.findings
    behavior_contract_signals = semver_state.behavior_contract_signals
    mode_used = base_classification.mode_used
    status = analysis_stage.status
    result = analysis_stage.result
    aggregation_trace = analysis_stage.aggregation_trace
    boundary_summary = analysis_stage.boundary_summary
    evidence_summary = analysis_stage.evidence_summary
    non_actionable_noise_ratio = analysis_stage.non_actionable_noise_ratio
    coverage_contract = analysis_stage.coverage_contract
    status_before_policy = analysis_stage.status_before_policy
    label_before_policy = analysis_stage.label_before_policy
    policy_effects = list(analysis_stage.policy_effects)
    policy_actions = list(analysis_stage.policy_actions)
    analysis_state = analysis_stage.analysis_state
    classification_source = analysis_stage.classification_source
    failure_category = analysis_stage.failure_category
    finalization = orchestrator_finalize.finalize_release(
        result=result,
        status=status,
        status_before_policy=status_before_policy,
        label_before_policy=label_before_policy,
        findings=findings,
        aggregation_trace=aggregation_trace,
        boundary_summary=boundary_summary,
        evidence_summary=evidence_summary,
        behavior_contract_signals=behavior_contract_signals,
        non_actionable_noise_ratio=non_actionable_noise_ratio,
        diff_result=diff_result,
        bumpkin_config=bumpkin_config,
        event_labels=event_labels,
        notes=local_notes,
        policy_effects=policy_effects,
        policy_actions=policy_actions,
        planner_payload=planner_decision.to_dict(),
        coverage_contract=coverage_contract,
    )
    semver_state.local_notes = finalization.notes
    semver_state.mode_used = mode_used
    semver_state.model_used = base_classification.model_used
    semver_state.result = finalization.result
    semver_state.aggregation_trace = aggregation_trace
    semver_state.fallback_reason = base_classification.fallback_reason
    semver_state.classification_source = classification_source
    semver_state.analysis_state = analysis_state
    semver_state.failure_category = failure_category
    semver_state.boundary_summary = boundary_summary
    semver_state.evidence_summary = evidence_summary
    semver_state.non_actionable_noise_ratio = non_actionable_noise_ratio
    semver_state.coverage_contract = coverage_contract
    semver_state.coverage_guard_triggered = analysis_stage.coverage_guard_triggered
    semver_state.truncated_no_bump_guard_triggered = (
        analysis_stage.truncated_no_bump_guard_triggered
    )
    semver_state.surface_area_guard_triggered = analysis_stage.surface_area_guard_triggered
    semver_state.large_pr_guard_triggered = analysis_stage.large_pr_guard_triggered
    semver_state.status_before_policy = status_before_policy
    semver_state.label_before_policy = label_before_policy
    semver_state.policy_effects = list(finalization.policy_effects)
    semver_state.policy_actions = list(finalization.policy_actions)
    semver_state.status = status
    semver_state.impact_summary = summarize_impact(diff_result.full_diff_text).to_dict()
    semver_state.override_summary = finalization.override_summary
    semver_state.override_status = finalization.override_status
    semver_state.override_payload = finalization.override_payload
    semver_state.current_tag = finalization.current_tag
    semver_state.next_tag = finalization.next_tag
    semver_state.decision_trace = finalization.decision_trace
    semver_state.planner_payload = planner_decision.to_dict()
    return semver_state
