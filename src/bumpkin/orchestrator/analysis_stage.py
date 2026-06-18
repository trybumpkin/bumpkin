from __future__ import annotations

from dataclasses import dataclass

from bumpkin.analysis.diffing import DiffResult
from bumpkin.analysis.findings import Finding, aggregate_findings
from bumpkin.config import BumpkinConfig
from bumpkin.contracts import build_coverage_contract
from bumpkin.orchestrator import adjudication as orchestrator_adjudication
from bumpkin.orchestrator import court_output as orchestrator_court_output
from bumpkin.policies import engine as policy_engine
from bumpkin.policies import guards as guard_policies


@dataclass(frozen=True)
class AnalysisStageArtifacts:
    result: dict[str, object]
    aggregation_trace: str | None
    boundary_summary: dict[str, int]
    evidence_summary: dict[str, int]
    non_actionable_noise_ratio: float
    coverage_contract: dict[str, object]
    coverage_guard_triggered: bool
    truncated_no_bump_guard_triggered: bool
    surface_area_guard_triggered: bool
    large_pr_guard_triggered: bool
    status_before_policy: str
    label_before_policy: str | None
    policy_effects: list[str]
    policy_actions: list[str]
    status: str
    analysis_state: str
    classification_source: str
    failure_category: str | None
    notes: list[str]


def apply_analysis_stage(
    *,
    result: dict[str, object],
    findings: list[Finding],
    behavior_contract_signals: dict[str, object],
    diff_result: DiffResult,
    bumpkin_config: BumpkinConfig,
    local_public_hints: list[str],
    chunking_meta: dict[str, object],
    mode_used: str,
    fallback_reason: str | None,
    scope_mismatch_detected: bool,
    notes: list[str],
) -> AnalysisStageArtifacts:
    local_notes = list(notes)
    local_result = dict(result)
    local_aggregation_trace: str | None = None
    boundary_summary = {"public": 0, "internal": 0, "unknown": 0}
    coverage_guard_triggered = False

    if not scope_mismatch_detected:
        aggregated_findings = aggregate_findings(findings)
        (
            local_result,
            local_aggregation_trace,
            classification_source,
        ) = orchestrator_adjudication.apply_findings_adjudication(
            local_result,
            aggregated_findings=aggregated_findings,
            mode_used=mode_used,
            notes=local_notes,
        )
        boundary_summary = policy_engine.summarize_boundary(
            findings, public_hints=local_public_hints
        )
        local_result, coverage_guard_triggered = guard_policies.apply_analysis_coverage_guard(
            local_result,
            analyzed_files=diff_result.analyzed_files,
            findings=findings,
            chunking_meta=chunking_meta,
            notes=local_notes,
        )
        if coverage_guard_triggered:
            classification_source = "coverage-guard"
    else:
        classification_source = "scope-mismatch-guard"

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

    local_result, policy_mode_effects, policy_actions = policy_engine.apply_policy_mode(
        local_result,
        boundary_summary=boundary_summary,
        config=bumpkin_config,
        notes=local_notes,
    )
    local_result, unknown_boundary_effects, unknown_boundary_actions = (
        policy_engine.apply_unknown_boundary_policy(
            local_result,
            boundary_summary=boundary_summary,
            config=bumpkin_config,
            notes=local_notes,
        )
    )
    policy_actions.extend(unknown_boundary_actions)
    local_result, impact_threshold_effects, impact_threshold_actions = (
        policy_engine.apply_impact_evidence_threshold(
            local_result,
            boundary_summary=boundary_summary,
            evidence_summary=evidence_summary,
            config=bumpkin_config,
            notes=local_notes,
        )
    )
    policy_actions.extend(impact_threshold_actions)
    local_result, noise_policy_effects, noise_policy_actions = (
        policy_engine.apply_noise_suppression_policy(
            local_result,
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

    local_result, truncated_no_bump_guard_triggered = guard_policies.apply_truncated_no_bump_guard(
        local_result,
        truncated=diff_result.truncated,
        analyzed_files=diff_result.analyzed_files,
        policy=bumpkin_config.truncated_no_bump_policy,
        notes=local_notes,
    )
    local_result, surface_area_guard_triggered = guard_policies.apply_truncated_surface_area_guard(
        local_result,
        truncated=diff_result.truncated,
        analyzed_files=diff_result.analyzed_files,
        surface_area_hints=local_public_hints,
        chunking_meta=chunking_meta,
        notes=local_notes,
    )
    local_result, large_pr_guard_triggered = guard_policies.apply_large_pr_no_bump_guard(
        local_result,
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
        if str(local_result.get("status", "classified")) == "classified":
            local_result = {
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

    status_before_policy = str(local_result.get("status", "classified"))
    label_before_policy = (
        str(local_result.get("label", "")).upper() if status_before_policy == "classified" else None
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
    local_result = orchestrator_court_output.apply_docs_only_policy(
        local_result,
        bumpkin_config,
        local_notes,
    )

    local_result, degraded_policy_effects, degraded_policy_actions = (
        policy_engine.apply_degraded_provider_policy(
            local_result,
            mode_used=mode_used,
            classification_source=classification_source,
            config=bumpkin_config,
            notes=local_notes,
        )
    )
    policy_actions.extend(degraded_policy_actions)
    policy_effects.extend(degraded_policy_effects)

    status = str(local_result.get("status", "classified"))
    if status not in {"classified", "manual_review"}:
        status = "manual_review"
    analysis_state, classification_source = orchestrator_adjudication.derive_analysis_state(
        status=status,
        classification_source=classification_source,
    )
    failure_category = orchestrator_adjudication.categorize_failure_reason(fallback_reason)

    return AnalysisStageArtifacts(
        result=local_result,
        aggregation_trace=local_aggregation_trace,
        boundary_summary=boundary_summary,
        evidence_summary=evidence_summary,
        non_actionable_noise_ratio=non_actionable_noise_ratio,
        coverage_contract=coverage_contract,
        coverage_guard_triggered=coverage_guard_triggered,
        truncated_no_bump_guard_triggered=truncated_no_bump_guard_triggered,
        surface_area_guard_triggered=surface_area_guard_triggered,
        large_pr_guard_triggered=large_pr_guard_triggered,
        status_before_policy=status_before_policy,
        label_before_policy=label_before_policy,
        policy_effects=policy_effects,
        policy_actions=policy_actions,
        status=status,
        analysis_state=analysis_state,
        classification_source=classification_source,
        failure_category=failure_category,
        notes=local_notes,
    )
