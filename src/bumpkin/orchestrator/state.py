from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bumpkin.analysis.diffing import DiffResult
from bumpkin.analysis.evidence import EvidenceItem
from bumpkin.analysis.findings import Finding
from bumpkin.orchestrator.analysis_stage import AnalysisStageArtifacts
from bumpkin.orchestrator.base_classification import BaseClassificationArtifacts
from bumpkin.orchestrator.court_setup import CourtSetupArtifacts


@dataclass
class CorePipelineState:
    diff_result: DiffResult
    behavior_contract_signals: dict[str, object]
    findings: list[Finding]
    evidence_items: list[EvidenceItem]
    evidence_summary_meta: dict[str, Any]
    chunking_meta: dict[str, object]
    base_classification: BaseClassificationArtifacts
    analysis_stage: AnalysisStageArtifacts
    local_notes: list[str]
    local_public_hints: list[str]
    scope_mismatch_detected: bool
    local_scope_guard: dict[str, object]
    result: dict[str, Any]
    mode_used: str = ""
    model_used: str | None = None
    aggregation_trace: str | None = None
    fallback_reason: str | None = None
    classification_source: str = ""
    analysis_state: str = ""
    failure_category: str | None = None
    boundary_summary: dict[str, int] = field(default_factory=dict)
    evidence_summary: dict[str, int] = field(default_factory=dict)
    non_actionable_noise_ratio: float = 0.0
    coverage_contract: dict[str, object] = field(default_factory=dict)
    coverage_guard_triggered: bool = False
    truncated_no_bump_guard_triggered: bool = False
    surface_area_guard_triggered: bool = False
    large_pr_guard_triggered: bool = False
    status_before_policy: str = ""
    label_before_policy: str | None = None
    policy_effects: list[str] = field(default_factory=list)
    policy_actions: list[str] = field(default_factory=list)
    status: str = "manual_review"
    impact_summary: dict[str, Any] = field(default_factory=dict)
    override_summary: str | None = None
    override_status: str = "none"
    override_payload: dict[str, str | bool | None] = field(default_factory=dict)
    current_tag: str | None = None
    next_tag: str | None = None
    decision_trace: dict[str, Any] = field(default_factory=dict)
    planner_payload: dict[str, Any] = field(default_factory=dict)
    case_file: dict[str, Any] = field(default_factory=dict)
    case_file_stats: dict[str, Any] = field(default_factory=dict)
    court_advisory: dict[str, Any] = field(default_factory=dict)
    deterministic_label: str | None = None
    deterministic_confidence: str | None = None
    deterministic_next_tag: str | None = None
    advisory_token: str = ""
    court_fallback_reason: str | None = None
    court_model_used: str | None = None
    court_skipped_reason: str | None = None
    court_setup_artifacts: CourtSetupArtifacts | None = None
    decision_authority: str = ""
    explainability_rows: list[dict[str, str]] = field(default_factory=list)
    semantic_facts: list[dict[str, Any]] = field(default_factory=list)
    proof_obligations: dict[str, Any] = field(default_factory=dict)
    reasoning_trace: list[dict[str, Any]] = field(default_factory=list)
    contradictions: list[dict[str, Any]] = field(default_factory=list)
