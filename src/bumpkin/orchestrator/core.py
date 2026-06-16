from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bumpkin.analysis import explanation_facts as explanation_dsl
from bumpkin.analysis import semantic_review
from bumpkin.analysis.case_file import build_case_file, render_case_file_text
from bumpkin.analysis.diffing import DiffResult
from bumpkin.analysis.evidence import build_evidence_items, summarize_evidence_items
from bumpkin.analysis.findings import (
    Finding,
    aggregate_findings,
    build_filesystem_workspace_loader,
    detect_semver_findings,
)
from bumpkin.analysis.impact import summarize_impact
from bumpkin.config import BumpkinConfig
from bumpkin.contracts import build_coverage_contract
from bumpkin.orchestrator import adjudication as orchestrator_adjudication
from bumpkin.orchestrator import court as orchestrator_court
from bumpkin.orchestrator import court_output as orchestrator_court_output
from bumpkin.orchestrator import explainability as orchestrator_explainability
from bumpkin.orchestrator import explanation_polish
from bumpkin.orchestrator import finalize as orchestrator_finalize
from bumpkin.planner import PlannerDecision
from bumpkin.policies import engine as policy_engine
from bumpkin.policies import guards as guard_policies
from bumpkin.prompt_pack import PromptPackMetadata
from bumpkin.providers.llm import get_no_bump_recommendation, get_stub_recommendation
from bumpkin.providers.semantic import semantic_fallback_recommendation
from bumpkin.versioning.tags import detect_next_version

_polish_explanation_with_model = explanation_polish.polish_explanation_with_model
_should_run_explanation_polish = explanation_polish.should_run_explanation_polish
_extract_polish_payload = explanation_polish.extract_polish_payload
_validate_polish_payload = explanation_polish.validate_polish_payload


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
_apply_docs_only_policy = orchestrator_court_output.apply_docs_only_policy
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

    fallback_reason: str | None = None
    mode_used = "deterministic-engine"
    model_used: str | None = None
    classification_source = "deterministic-engine"
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
    aggregation_trace: str | None = None
    boundary_summary = {"public": 0, "internal": 0, "unknown": 0}
    coverage_contract: dict[str, object] = {
        "version": "coverage_contract_v1",
        "status": "pass",
        "critical_files_total": 0,
        "critical_files_covered": 0,
        "omitted_critical_files": [],
        "omitted_files_total": 0,
    }
    policy_actions: list[str] = []
    coverage_guard_triggered = False

    if scope_mismatch_detected:
        result: dict[str, object] = {
            "status": "manual_review",
            "label": None,
            "confidence": None,
            "reasoning": "Analysis could not be reliably scoped to PR files.",
            "changelog": None,
        }
        mode_used = "scope-guard"
        model_used = "scope-guard"
        fallback_reason = scope_mismatch_reason
        classification_source = "scope-mismatch-guard"
    elif diff_result.diff_text:
        aggregated_findings = aggregate_findings(findings)
        if mode.strip().lower() == "stub":
            result = get_stub_recommendation(truncated=diff_result.truncated)
            mode_used = "stub"
            model_used = "stub"
            classification_source = orchestrator_adjudication.source_from_mode(mode_used)
        elif aggregated_findings is not None:
            result = aggregated_findings.to_result_dict()
            aggregation_trace = aggregated_findings.aggregation_trace
            mode_used = "deterministic-findings"
            classification_source = "deterministic-findings"
            local_notes.append("Deterministic findings engine produced base classification.")
        else:
            result = semantic_fallback_recommendation(
                diff_text=diff_result.diff_text,
                surface_area_hints=local_public_hints,
                truncated=diff_result.truncated,
            )
            mode_used = "deterministic-heuristic"
            classification_source = "deterministic-heuristic"
            local_notes.append("Deterministic semantic heuristic produced base classification.")
    else:
        result = get_no_bump_recommendation(truncated=diff_result.truncated)
        mode_used = "deterministic-no-diff"
        model_used = "heuristic"
        classification_source = "deterministic-no-diff"

    if not scope_mismatch_detected:
        aggregated_findings = aggregate_findings(findings)
        result, aggregation_trace, classification_source = (
            orchestrator_adjudication.apply_findings_adjudication(
                result,
                aggregated_findings=aggregated_findings,
                mode_used=mode_used,
                notes=local_notes,
            )
        )
        boundary_summary = policy_engine.summarize_boundary(
            findings, public_hints=local_public_hints
        )
        result, coverage_guard_triggered = guard_policies.apply_analysis_coverage_guard(
            result,
            analyzed_files=diff_result.analyzed_files,
            findings=findings,
            chunking_meta=chunking_meta,
            notes=local_notes,
        )
        if coverage_guard_triggered:
            classification_source = "coverage-guard"

    evidence_summary = policy_engine.summarize_evidence(
        findings,
        public_hints=local_public_hints,
        contract_signals=behavior_contract_signals,
    )
    non_actionable_noise_ratio = 0.0
    if diff_result.changed_files_total > 0:
        non_actionable_noise_ratio = round(
            diff_result.ignored_files_total / diff_result.changed_files_total,
            4,
        )

    result, policy_mode_effects, policy_actions = policy_engine.apply_policy_mode(
        result,
        boundary_summary=boundary_summary,
        config=bumpkin_config,
        notes=local_notes,
    )
    result, unknown_boundary_effects, unknown_boundary_actions = (
        policy_engine.apply_unknown_boundary_policy(
            result,
            boundary_summary=boundary_summary,
            config=bumpkin_config,
            notes=local_notes,
        )
    )
    policy_actions.extend(unknown_boundary_actions)
    result, impact_threshold_effects, impact_threshold_actions = (
        policy_engine.apply_impact_evidence_threshold(
            result,
            boundary_summary=boundary_summary,
            evidence_summary=evidence_summary,
            config=bumpkin_config,
            notes=local_notes,
        )
    )
    policy_actions.extend(impact_threshold_actions)
    result, noise_policy_effects, noise_policy_actions = (
        policy_engine.apply_noise_suppression_policy(
            result,
            noise_ratio=non_actionable_noise_ratio,
            changed_files_total=diff_result.changed_files_total,
            evidence_summary=evidence_summary,
            config=bumpkin_config,
            notes=local_notes,
        )
    )
    policy_actions.extend(noise_policy_actions)
    if findings:
        local_notes.append(
            "Boundary summary: "
            f"public={boundary_summary['public']}, "
            f"internal={boundary_summary['internal']}, "
            f"unknown={boundary_summary['unknown']}."
        )

    result, truncated_no_bump_guard_triggered = guard_policies.apply_truncated_no_bump_guard(
        result,
        truncated=diff_result.truncated,
        analyzed_files=diff_result.analyzed_files,
        policy=bumpkin_config.truncated_no_bump_policy,
        notes=local_notes,
    )
    result, surface_area_guard_triggered = guard_policies.apply_truncated_surface_area_guard(
        result,
        truncated=diff_result.truncated,
        analyzed_files=diff_result.analyzed_files,
        surface_area_hints=local_public_hints,
        chunking_meta=chunking_meta,
        notes=local_notes,
    )
    result, large_pr_guard_triggered = guard_policies.apply_large_pr_no_bump_guard(
        result,
        analyzed_files_count=len(diff_result.analyzed_files),
        approx_prompt_tokens=diff_result.approx_prompt_tokens,
        max_files=bumpkin_config.large_pr_max_files,
        max_tokens=bumpkin_config.large_pr_max_tokens,
        policy=bumpkin_config.truncated_no_bump_policy,
        notes=local_notes,
    )

    coverage_contract = build_coverage_contract(
        analyzed_files=diff_result.analyzed_files,
        chunking_meta=chunking_meta,
        public_api_hints=local_public_hints,
        behavior_contract_signals=behavior_contract_signals,
    )
    if coverage_contract["status"] == "fail":
        local_notes.append(
            "Coverage contract failed: omitted critical files require manual review."
        )
        if str(result.get("status", "classified")) == "classified":
            result = {
                "status": "manual_review",
                "label": None,
                "confidence": None,
                "reasoning": (
                    "Critical coverage requirements were not met. "
                    "Manual review is required before SemVer classification."
                ),
                "changelog": None,
            }
            classification_source = "coverage-contract"
            coverage_guard_triggered = True

    status_before_policy = str(result.get("status", "classified"))
    label_before_policy = (
        str(result.get("label", "")).upper() if status_before_policy == "classified" else None
    )
    policy_effects: list[str] = (
        list(policy_mode_effects)
        + list(unknown_boundary_effects)
        + list(impact_threshold_effects)
        + list(noise_policy_effects)
    )
    policy_effects.append(
        policy_engine.derive_docs_only_policy_effect(
            status=status_before_policy,
            label=label_before_policy,
            docs_only_label=bumpkin_config.docs_only_label,
        )
    )
    result = _apply_docs_only_policy(result, bumpkin_config, local_notes)

    result, degraded_policy_effects, degraded_policy_actions = (
        policy_engine.apply_degraded_provider_policy(
            result,
            mode_used=mode_used,
            classification_source=classification_source,
            config=bumpkin_config,
            notes=local_notes,
        )
    )
    policy_actions.extend(degraded_policy_actions)
    policy_effects.extend(degraded_policy_effects)

    status = str(result.get("status", "classified"))
    if status not in {"classified", "manual_review"}:
        status = "manual_review"
    analysis_state, classification_source = orchestrator_adjudication.derive_analysis_state(
        status=status,
        classification_source=classification_source,
    )
    failure_category = orchestrator_adjudication.categorize_failure_reason(fallback_reason)

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

    case_file_build = build_case_file(
        engine_result=result,
        findings=findings,
        evidence_items=evidence_items,
        policy_effects=policy_effects,
        notes=local_notes,
        coverage_contract=coverage_contract,
        boundary_summary=boundary_summary,
        evidence_summary=evidence_summary,
    )
    case_file = case_file_build.case_file
    case_file_stats = case_file_build.stats
    pre_court_result = dict(result)
    pre_court_status = str(pre_court_result.get("status", "manual_review"))
    deterministic_label = (
        str(pre_court_result.get("label", "")).upper() if pre_court_status == "classified" else None
    )
    deterministic_confidence = str(pre_court_result.get("confidence", "")).strip().lower() or None
    deterministic_next_tag = next_tag if pre_court_status == "classified" else None
    advisory_token = token if planner_decision.allow_model_call else ""

    should_skip_court, court_skipped_reason = _should_skip_court_advisory(
        status=pre_court_status,
        deterministic_label=deterministic_label,
        deterministic_confidence=deterministic_confidence,
        mode_used=mode_used,
        classification_source=classification_source,
    )
    if should_skip_court and court_skipped_reason:
        court_advisory = _build_skipped_court_advisory(
            deterministic_label=deterministic_label,
            deterministic_confidence=deterministic_confidence,
            court_skipped_reason=court_skipped_reason,
        )
        court_fallback_reason = None
        court_model_used = None
        local_notes.append(f"Court advisory skipped: {court_skipped_reason}.")
    else:
        court_skipped_reason = None
        court_advisory, court_fallback_reason, court_model_used = (
            orchestrator_court.run_court_advisory(
                mode=mode,
                model=model,
                fallback_model=fallback_model or None,
                endpoint=endpoint,
                token=advisory_token,
                max_retries=max_retries,
                request_timeout=request_timeout,
                engine_label=deterministic_label,
                case_file_text=render_case_file_text(case_file),
                language_hints=language_hints,
            )
        )

    if court_model_used:
        local_notes.append(f"Compatibility court analyzed by model: {court_model_used}.")
    if court_fallback_reason:
        local_notes.append(f"Compatibility court advisory degraded: {court_fallback_reason}.")
    if str(court_advisory.get("status", "")).lower() == "manual_review":
        reason = str(court_advisory.get("disagreement_reason", "")).strip()
        if reason:
            local_notes.append(reason)

    decision_authority = bumpkin_config.decision_authority_mode
    if decision_authority == "court":
        advisory_status = str(court_advisory.get("status", "")).strip().lower()
        advisory_label = str(court_advisory.get("label", "")).strip().upper()
        if advisory_status in {"aligned", "manual_review"} and advisory_label in {
            "MAJOR",
            "MINOR",
            "PATCH",
            "NO_BUMP",
        }:
            evidence_lookup = _case_file_evidence_lookup(case_file)
            using_accepted_evidence_ids = _uses_accepted_evidence_ids(
                court_advisory=court_advisory,
                evidence_lookup=evidence_lookup,
            )
            selected_records = _select_explanation_records(
                advisory_label=advisory_label,
                court_advisory=court_advisory,
                evidence_lookup=evidence_lookup,
                max_items=3,
            )
            selected_reasoning, used_evidence_reasoning = _render_evidence_grounded_reasoning(
                advisory_label=advisory_label,
                court_advisory=court_advisory,
                evidence_lookup=evidence_lookup,
            )
            selected_changelog, used_evidence_changelog = _render_evidence_grounded_changelog(
                advisory_label=advisory_label,
                court_advisory=court_advisory,
                evidence_lookup=evidence_lookup,
            )
            used_deterministic_reasoning = False
            used_deterministic_changelog = False
            if not selected_reasoning:
                selected_reasoning, used_deterministic_reasoning = _select_court_reasoning(
                    court_advisory=court_advisory,
                    advisory_label=advisory_label,
                    pre_court_result=pre_court_result,
                )
            if not selected_changelog:
                selected_changelog, used_deterministic_changelog = _select_court_changelog(
                    advisory_label=advisory_label,
                    court_advisory=court_advisory,
                    pre_court_result=pre_court_result,
                )
            polish_applied = False
            polish_failure_reason: str | None = None
            confidence_text = str(court_advisory.get("confidence", "low")).strip().lower() or "low"
            if _should_run_explanation_polish(
                reasoning=selected_reasoning,
                changelog=selected_changelog,
                confidence=confidence_text,
                token=advisory_token,
            ):
                polish_reasoning, polish_changelog, polish_applied, polish_failure_reason = (
                    _polish_explanation_with_model(
                        advisory_label=advisory_label,
                        draft_reasoning=selected_reasoning,
                        draft_changelog=selected_changelog,
                        records=selected_records,
                        token=advisory_token,
                        endpoint=endpoint,
                        model=court_model_used or model,
                        max_retries=max_retries,
                        request_timeout=request_timeout,
                    )
                )
                selected_reasoning = polish_reasoning
                selected_changelog = polish_changelog
            explicit_regenerated = False
            selected_reasoning, selected_changelog, explicit_regenerated = (
                _enforce_explicit_explanation(
                    advisory_label=advisory_label,
                    reasoning=selected_reasoning,
                    changelog=selected_changelog,
                    records=selected_records,
                    fallback_paths=diff_result.analyzed_files,
                )
            )
            result = {
                "status": "classified",
                "label": advisory_label,
                "confidence": confidence_text,
                "reasoning": selected_reasoning,
                "changelog": selected_changelog,
            }
            status = "classified"
            classification_source = "court"
            analysis_state = "authoritative"
            failure_category = None
            if used_deterministic_reasoning:
                local_notes.append(
                    "Court authority reused deterministic reasoning because court explanation was generic or low-confidence."
                )
            elif used_evidence_reasoning:
                if using_accepted_evidence_ids:
                    local_notes.append(
                        "Court authority generated reasoning from accepted evidence IDs."
                    )
                else:
                    local_notes.append(
                        "Court authority generated reasoning from deterministic evidence fallback records."
                    )
            if used_deterministic_changelog:
                local_notes.append(
                    "Court authority reused deterministic changelog because court explanation was generic or low-confidence."
                )
            elif used_evidence_changelog:
                if using_accepted_evidence_ids:
                    local_notes.append(
                        "Court authority generated changelog from accepted evidence IDs."
                    )
                else:
                    local_notes.append(
                        "Court authority generated changelog from deterministic evidence fallback records."
                    )
            if polish_applied:
                local_notes.append("Applied low-token explanation polish pass for readability.")
            elif polish_failure_reason:
                local_notes.append(
                    f"Explanation polish skipped/failed; kept deterministic wording ({polish_failure_reason})."
                )
            if explicit_regenerated:
                local_notes.append(
                    "Explicitness gate regenerated reasoning/changelog to include concrete file anchors and action verbs."
                )
            if advisory_label != deterministic_label:
                local_notes.append(
                    f"Court authority applied: deterministic {deterministic_label} -> court {advisory_label}."
                )
            if advisory_label != "NO_BUMP":
                current_tag, next_tag, court_version_notes = detect_next_version(
                    advisory_label,
                    pre_1_0_breaking_as_minor=bumpkin_config.pre_1_0_breaking_as_minor,
                )
                local_notes.extend(court_version_notes)
            else:
                next_tag = None
        elif advisory_status in {"degraded", "skipped"} and pre_court_status == "classified":
            result = pre_court_result
            status = "classified"
            classification_source = "deterministic-court-fallback"
            analysis_state = (
                "degraded_fallback" if advisory_status == "degraded" else "authoritative"
            )
            if advisory_status == "degraded":
                failure_category = (
                    orchestrator_adjudication.categorize_failure_reason(court_fallback_reason)
                    or failure_category
                )
            next_tag = deterministic_next_tag
            if advisory_status == "degraded":
                local_notes.append(
                    "Court authority degraded; using pre-court deterministic classification as fallback."
                )
            else:
                local_notes.append(
                    "Court authority skipped; using pre-court deterministic classification."
                )
        else:
            result = {
                "status": "manual_review",
                "label": None,
                "confidence": None,
                "reasoning": (
                    "Compatibility court is configured as final authority, but no reliable court verdict "
                    "was available. Manual review is required."
                ),
                "changelog": None,
            }
            status = "manual_review"
            classification_source = "court-unavailable"
            analysis_state = "manual_review"
            next_tag = None
            local_notes.append(
                "Court authority mode forced manual review because advisory status was not authoritative."
            )

    explainability_rows: list[dict[str, str]] = []
    if status == "classified":
        final_label = str(result.get("label", "")).strip().upper()
        evidence_lookup_for_rows = _case_file_evidence_lookup(case_file)
        explainability_rows = _build_explainability_rows(
            advisory_label=final_label,
            court_advisory=court_advisory,
            evidence_lookup=evidence_lookup_for_rows,
            analyzed_files=diff_result.analyzed_files,
            diff_text=diff_result.full_diff_text,
            max_items=8,
        )
        semantic_rows = explanation_dsl.filter_semantic_delta_rows(explainability_rows)
        if not semantic_rows:
            result = {
                "status": "manual_review",
                "label": None,
                "confidence": None,
                "reasoning": (
                    "Explainability contract is unsatisfied because deterministic DSL "
                    "did not emit semantic delta rows. Manual review is required."
                ),
                "changelog": None,
            }
            status = "manual_review"
            classification_source = "explainability-contract"
            analysis_state = "manual_review"
            failure_category = "explainability_semantic_contract_unsatisfied"
            next_tag = None
            explainability_rows = []
            local_notes.append(
                "Fail-closed explainability gate triggered: only path-level or empty explainability rows were available."
            )
        else:
            explainability_rows = semantic_rows

    semantic_facts = explanation_dsl.filter_semantic_delta_rows(explainability_rows)
    evaluated_label_for_obligations = (
        str(result.get("label", "")).strip().upper()
        if status == "classified"
        else (str(court_advisory.get("label", "")).strip().upper() or deterministic_label)
    )
    proof_obligations = _evaluate_proof_obligations(
        status=status,
        evaluated_label=evaluated_label_for_obligations,
        semantic_facts=semantic_facts,
    )
    critical_missing_obligations = _critical_missing_proof_obligations(proof_obligations)
    if status == "classified" and critical_missing_obligations:
        result = {
            "status": "manual_review",
            "label": None,
            "confidence": None,
            "reasoning": (
                "Proof-obligation contract is unsatisfied because critical obligations are missing "
                f"({', '.join(critical_missing_obligations)}). Manual review is required."
            ),
            "changelog": None,
        }
        status = "manual_review"
        classification_source = "proof-obligation-contract"
        analysis_state = "manual_review"
        failure_category = failure_category or "proof_obligation_contract_unsatisfied"
        next_tag = None
        local_notes.append(
            "Fail-closed proof-obligation gate triggered: classified output downgraded to manual_review."
        )
    proof_obligations["status"] = status
    final_label_for_trace = (
        str(result.get("label", "")).strip().upper() if status == "classified" else None
    )
    contradictions = _detect_contradictions(
        event_labels=labels,
        semantic_facts=semantic_facts,
        status=status,
        final_label=final_label_for_trace,
    )
    semantic_facts = _prioritize_semantic_facts(
        semantic_facts,
        contradiction_paths=_extract_contradiction_paths(contradictions),
        max_items=8,
    )
    if status == "classified":
        explainability_rows = list(semantic_facts)
    reasoning_trace = _build_reasoning_trace(
        semantic_facts=semantic_facts,
        policy_effects=policy_effects,
        contradictions=contradictions,
        final_label=final_label_for_trace,
    )

    decision_trace["decision_authority"] = decision_authority
    decision_trace["deterministic_label"] = deterministic_label
    decision_trace["deterministic_next_tag"] = deterministic_next_tag
    decision_trace["court_skipped_reason"] = court_skipped_reason
    decision_trace["explainability_rows"] = len(explainability_rows)
    decision_trace["court"] = {
        "status": court_advisory.get("status"),
        "label": court_advisory.get("label"),
        "confidence": court_advisory.get("confidence"),
    }
    decision_trace["proof_obligations_missing"] = len(proof_obligations.get("missing", []))
    decision_trace["reasoning_trace_claims"] = len(reasoning_trace)
    decision_trace["contradiction_count"] = len(contradictions)

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
        scope_guard=local_scope_guard,
        non_actionable_noise_ratio=non_actionable_noise_ratio,
        chunking_meta=chunking_meta,
        planner_payload=planner_decision.to_dict(),
        coverage_contract=coverage_contract,
        evidence_items=[item.to_dict() for item in evidence_items],
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
        notes=local_notes,
    )
    output["court_skipped_reason"] = court_skipped_reason
    output["court_fallback_reason"] = court_fallback_reason

    return CoreAnalysisResult(
        output=output,
        result=result,
        notes=local_notes,
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
