from __future__ import annotations

from bumpkin.analysis import semantic_review
from bumpkin.analysis.diffing import DiffResult
from bumpkin.analysis.evidence import build_evidence_items, summarize_evidence_items
from bumpkin.analysis.findings import (
    build_filesystem_workspace_loader,
    detect_semver_findings,
)
from bumpkin.analysis.impact import summarize_impact
from bumpkin.config import BumpkinConfig
from bumpkin.orchestrator import analysis_stage as orchestrator_analysis_stage
from bumpkin.orchestrator import base_classification as orchestrator_base_classification
from bumpkin.orchestrator import court_authority as orchestrator_court_authority
from bumpkin.orchestrator import court_output as orchestrator_court_output
from bumpkin.orchestrator import court_setup as orchestrator_court_setup
from bumpkin.orchestrator import explainability as orchestrator_explainability
from bumpkin.orchestrator import explanation_polish
from bumpkin.orchestrator import finalize as orchestrator_finalize
from bumpkin.orchestrator import output_assembly as orchestrator_output_assembly
from bumpkin.orchestrator import postprocess as orchestrator_postprocess
from bumpkin.planner import PlannerDecision
from bumpkin.policies import engine as policy_engine
from bumpkin.prompt_pack import PromptPackMetadata

CoreAnalysisResult = orchestrator_output_assembly.CoreAnalysisResult

_polish_explanation_with_model = explanation_polish.polish_explanation_with_model
_should_run_explanation_polish = explanation_polish.should_run_explanation_polish
_extract_polish_payload = explanation_polish.extract_polish_payload
_validate_polish_payload = explanation_polish.validate_polish_payload


def _workspace_loader_for_diff_result(diff_result: DiffResult):
    repo_root = (diff_result.repo_root or "").strip()
    if not repo_root:
        return None
    return build_filesystem_workspace_loader(repo_root)


_changelog_for_label = orchestrator_explainability.changelog_for_label
_case_file_evidence_lookup = orchestrator_explainability.case_file_evidence_lookup
_derive_scope_from_path = orchestrator_explainability.derive_scope_from_path
_summarize_path_targets = orchestrator_explainability.summarize_path_targets
_extract_symbol_hint = orchestrator_explainability.extract_symbol_hint
_derive_operation_hint = orchestrator_explainability.derive_operation_hint
_change_hint_from_records = orchestrator_explainability.change_hint_from_records
_file_anchors_from_records = orchestrator_explainability.file_anchors_from_records
_merge_anchor_records = orchestrator_explainability.merge_anchor_records
_contains_action_verb = orchestrator_explainability.contains_action_verb
_is_template_reasoning = orchestrator_explainability.is_template_reasoning
_passes_explicitness_gate = orchestrator_explainability.passes_explicitness_gate
_build_explicit_fallback_explanation = (
    orchestrator_explainability.build_explicit_fallback_explanation
)
_enforce_explicit_explanation = orchestrator_explainability.enforce_explicit_explanation
_evidence_priority = orchestrator_explainability.evidence_priority
_select_explanation_records = orchestrator_explainability.select_explanation_records
_is_non_runtime_path = orchestrator_explainability.is_non_runtime_path
_extract_before_after_by_path = orchestrator_explainability.extract_before_after_by_path
_build_patch_fallback_records = orchestrator_explainability.build_patch_fallback_records
_build_no_bump_invariance_records = orchestrator_explainability.build_no_bump_invariance_records
_build_explainability_rows = orchestrator_explainability.build_explainability_rows
_row_has_semantic_transition = semantic_review.row_has_semantic_transition
_row_satisfies_patch_transition = semantic_review.row_satisfies_patch_transition
_evaluate_proof_obligations = semantic_review.evaluate_proof_obligations
_critical_missing_proof_obligations = semantic_review.critical_missing_proof_obligations
_semantic_severity_rank = semantic_review.semantic_severity_rank
_extract_contradiction_paths = semantic_review.extract_contradiction_paths
_prioritize_semantic_facts = semantic_review.prioritize_semantic_facts
_normalize_policy_id = semantic_review.normalize_policy_id
_build_reasoning_trace = semantic_review.build_reasoning_trace
_detect_contradictions = semantic_review.detect_contradictions
_uses_accepted_evidence_ids = orchestrator_court_output.uses_accepted_evidence_ids
_reasoning_intro_for_label = orchestrator_court_output.reasoning_intro_for_label
_render_evidence_grounded_reasoning = orchestrator_court_output.render_evidence_grounded_reasoning
_render_evidence_grounded_changelog = orchestrator_court_output.render_evidence_grounded_changelog
_is_generic_court_summary = orchestrator_court_output.is_generic_court_summary
_prefer_deterministic_explanation = orchestrator_court_output.prefer_deterministic_explanation
_select_court_reasoning = orchestrator_court_output.select_court_reasoning
_select_court_changelog = orchestrator_court_output.select_court_changelog
_should_skip_court_advisory = orchestrator_court_output.should_skip_court_advisory
_build_skipped_court_advisory = orchestrator_court_output.build_skipped_court_advisory


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
    local_notes = list(notes or [])
    labels = list(event_labels or [])
    local_public_hints = policy_engine.dedupe_preserving_order(list(public_api_hints or []))
    local_scope_guard = dict(scope_guard or {})

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
    result = base_classification.result
    aggregation_trace = base_classification.aggregation_trace
    fallback_reason = base_classification.fallback_reason
    mode_used = base_classification.mode_used
    model_used = base_classification.model_used
    classification_source = base_classification.classification_source
    local_notes = base_classification.notes

    analysis_stage = orchestrator_analysis_stage.apply_analysis_stage(
        result=result,
        findings=findings,
        behavior_contract_signals=behavior_contract_signals,
        diff_result=diff_result,
        bumpkin_config=bumpkin_config,
        local_public_hints=local_public_hints,
        chunking_meta=chunking_meta,
        mode_used=mode_used,
        fallback_reason=fallback_reason,
        scope_mismatch_detected=scope_mismatch_detected,
        notes=local_notes,
    )
    result = analysis_stage.result
    aggregation_trace = analysis_stage.aggregation_trace
    boundary_summary = analysis_stage.boundary_summary
    evidence_summary = analysis_stage.evidence_summary
    non_actionable_noise_ratio = analysis_stage.non_actionable_noise_ratio
    coverage_contract = analysis_stage.coverage_contract
    coverage_guard_triggered = analysis_stage.coverage_guard_triggered
    truncated_no_bump_guard_triggered = analysis_stage.truncated_no_bump_guard_triggered
    surface_area_guard_triggered = analysis_stage.surface_area_guard_triggered
    large_pr_guard_triggered = analysis_stage.large_pr_guard_triggered
    status_before_policy = analysis_stage.status_before_policy
    label_before_policy = analysis_stage.label_before_policy
    policy_effects = analysis_stage.policy_effects
    policy_actions = analysis_stage.policy_actions
    status = analysis_stage.status
    analysis_state = analysis_stage.analysis_state
    classification_source = analysis_stage.classification_source
    failure_category = analysis_stage.failure_category
    local_notes = analysis_stage.notes

    if mode_used == "deterministic-findings":
        local_notes.append("Deterministic findings selected the base SemVer classification.")
    elif mode_used == "deterministic-heuristic":
        local_notes.append(
            "Deterministic semantic heuristic selected the base SemVer classification."
        )
    elif mode_used == "deterministic-no-diff":
        local_notes.append(
            "No diff content detected; deterministic NO_BUMP classification applied."
        )
    elif mode_used == "scope-guard":
        local_notes.append(
            "Scope mismatch guard blocked automated classification; manual review required."
        )
    elif mode_used == "stub":
        local_notes.append("Stub mode selected for deterministic base classification.")
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

    impact_summary = summarize_impact(diff_result.full_diff_text).to_dict()

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
        event_labels=labels,
        notes=local_notes,
        policy_effects=policy_effects,
        policy_actions=policy_actions,
        planner_payload=planner_decision.to_dict(),
        coverage_contract=coverage_contract,
    )
    result = finalization.result
    local_notes = finalization.notes
    policy_effects = finalization.policy_effects
    override_summary = finalization.override_summary
    override_status = finalization.override_status
    override_payload = finalization.override_payload
    current_tag = finalization.current_tag
    next_tag = finalization.next_tag
    decision_trace = finalization.decision_trace

    court_setup_artifacts = orchestrator_court_setup.prepare_court_setup(
        result=result,
        findings=findings,
        evidence_items=evidence_items,
        policy_effects=policy_effects,
        notes=local_notes,
        coverage_contract=coverage_contract,
        boundary_summary=boundary_summary,
        evidence_summary=evidence_summary,
        allow_model_call=planner_decision.allow_model_call,
        token=token,
        mode=mode,
        model=model,
        fallback_model=fallback_model,
        endpoint=endpoint,
        max_retries=max_retries,
        request_timeout=request_timeout,
        language_hints=language_hints,
        classification_source=classification_source,
        mode_used=mode_used,
        next_tag=next_tag,
    )
    case_file = court_setup_artifacts.case_file
    case_file_stats = court_setup_artifacts.case_file_stats
    pre_court_result = court_setup_artifacts.pre_court_result
    pre_court_status = court_setup_artifacts.pre_court_status
    deterministic_label = court_setup_artifacts.deterministic_label
    deterministic_next_tag = court_setup_artifacts.deterministic_next_tag
    advisory_token = court_setup_artifacts.advisory_token
    court_advisory = court_setup_artifacts.court_advisory
    court_fallback_reason = court_setup_artifacts.court_fallback_reason
    court_model_used = court_setup_artifacts.court_model_used
    court_skipped_reason = court_setup_artifacts.court_skipped_reason
    local_notes = court_setup_artifacts.notes

    decision_authority = bumpkin_config.decision_authority_mode
    court_authority_artifacts = orchestrator_court_authority.apply_court_authority(
        decision_authority=decision_authority,
        court_advisory=court_advisory,
        case_file=case_file,
        pre_court_result=pre_court_result,
        pre_court_status=pre_court_status,
        deterministic_label=deterministic_label,
        deterministic_next_tag=deterministic_next_tag,
        court_fallback_reason=court_fallback_reason,
        court_model_used=court_model_used,
        advisory_token=advisory_token,
        endpoint=endpoint,
        model=model,
        max_retries=max_retries,
        request_timeout=request_timeout,
        diff_result=diff_result,
        pre_1_0_breaking_as_minor=bumpkin_config.pre_1_0_breaking_as_minor,
        result=result,
        status=status,
        classification_source=classification_source,
        analysis_state=analysis_state,
        failure_category=failure_category,
        current_tag=current_tag,
        next_tag=next_tag,
        notes=local_notes,
    )
    result = court_authority_artifacts.result
    status = court_authority_artifacts.status
    classification_source = court_authority_artifacts.classification_source
    analysis_state = court_authority_artifacts.analysis_state
    failure_category = court_authority_artifacts.failure_category
    current_tag = court_authority_artifacts.current_tag
    next_tag = court_authority_artifacts.next_tag
    local_notes = court_authority_artifacts.notes

    decision_trace["decision_authority"] = decision_authority
    decision_trace["deterministic_label"] = deterministic_label
    decision_trace["deterministic_next_tag"] = deterministic_next_tag
    semantic_trace_artifacts = orchestrator_postprocess.build_semantic_trace_artifacts(
        result=result,
        status=status,
        court_advisory=court_advisory,
        case_file=case_file,
        diff_result=diff_result,
        event_labels=labels,
        policy_effects=policy_effects,
        decision_trace=decision_trace,
        classification_source=classification_source,
        analysis_state=analysis_state,
        failure_category=failure_category,
        next_tag=next_tag,
        notes=local_notes,
        deterministic_label=deterministic_label,
        court_skipped_reason=court_skipped_reason,
    )
    result = semantic_trace_artifacts.result
    status = semantic_trace_artifacts.status
    classification_source = semantic_trace_artifacts.classification_source
    analysis_state = semantic_trace_artifacts.analysis_state
    failure_category = semantic_trace_artifacts.failure_category
    next_tag = semantic_trace_artifacts.next_tag
    local_notes = semantic_trace_artifacts.notes
    decision_trace = semantic_trace_artifacts.decision_trace
    explainability_rows = semantic_trace_artifacts.explainability_rows
    semantic_facts = semantic_trace_artifacts.semantic_facts
    proof_obligations = semantic_trace_artifacts.proof_obligations
    reasoning_trace = semantic_trace_artifacts.reasoning_trace
    contradictions = semantic_trace_artifacts.contradictions

    return orchestrator_output_assembly.assemble_core_analysis_result(
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
        scope_guard=local_scope_guard,
        non_actionable_noise_ratio=non_actionable_noise_ratio,
        chunking_meta=chunking_meta,
        planner_payload=planner_decision.to_dict(),
        coverage_contract=coverage_contract,
        evidence_items=[item.to_dict() for item in evidence_items],
        evidence_summary_meta=evidence_summary_meta,
        case_file=case_file,
        case_file_stats=case_file_stats,
        court_advisory=court_advisory,
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
        notes=local_notes,
        court_skipped_reason=court_skipped_reason,
        court_fallback_reason=court_fallback_reason,
        override_summary=override_summary,
        override_status=override_status,
        court_model_used=court_model_used,
    )
