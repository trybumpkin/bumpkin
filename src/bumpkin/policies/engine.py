"""Stable policy imports grouped by policy responsibility.

The implementations live in focused modules; this facade preserves the
historical ``bumpkin.policies.engine`` import path for callers.
"""

from .adjustments import (
    apply_degraded_provider_policy,
    apply_impact_evidence_threshold,
    apply_noise_suppression_policy,
    apply_policy_mode,
    apply_unknown_boundary_policy,
    derive_docs_only_policy_effect,
    derive_pre_1_0_policy_effect,
    has_bugfix_intent,
    manual_review_result,
)
from .boundaries import (
    classify_finding_boundary,
    dedupe_preserving_order,
    finding_severity_counts,
    path_matches_hints,
    summarize_boundary,
)
from .evidence import detect_behavior_contract_signals, summarize_evidence

__all__ = [
    "apply_degraded_provider_policy",
    "apply_impact_evidence_threshold",
    "apply_noise_suppression_policy",
    "apply_policy_mode",
    "apply_unknown_boundary_policy",
    "classify_finding_boundary",
    "dedupe_preserving_order",
    "derive_docs_only_policy_effect",
    "derive_pre_1_0_policy_effect",
    "detect_behavior_contract_signals",
    "finding_severity_counts",
    "has_bugfix_intent",
    "manual_review_result",
    "path_matches_hints",
    "summarize_boundary",
    "summarize_evidence",
]
