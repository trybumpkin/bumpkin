"""Compatibility resolver for helpers historically exposed by ``core``."""

from __future__ import annotations

from typing import Any

from bumpkin.analysis import semantic_review
from bumpkin.orchestrator import court_output, explainability, explanation_polish

_MODULES = {
    "semantic_review": semantic_review,
    "court_output": court_output,
    "explanation_polish": explanation_polish,
    "explainability": explainability,
}
_SOURCES = {
    **{
        name: (explainability, name)
        for name in (
            "changelog_for_label",
            "case_file_evidence_lookup",
            "derive_scope_from_path",
            "summarize_path_targets",
            "extract_symbol_hint",
            "derive_operation_hint",
            "change_hint_from_records",
            "file_anchors_from_records",
            "merge_anchor_records",
            "contains_action_verb",
            "is_template_reasoning",
            "passes_explicitness_gate",
            "build_explicit_fallback_explanation",
            "enforce_explicit_explanation",
            "evidence_priority",
            "select_explanation_records",
            "is_non_runtime_path",
            "extract_before_after_by_path",
            "build_patch_fallback_records",
            "build_no_bump_invariance_records",
            "build_explainability_rows",
        )
    },
    **{
        name: (semantic_review, name)
        for name in (
            "row_has_semantic_transition",
            "row_satisfies_patch_transition",
            "evaluate_proof_obligations",
            "critical_missing_proof_obligations",
            "semantic_severity_rank",
            "extract_contradiction_paths",
            "prioritize_semantic_facts",
            "normalize_policy_id",
            "build_reasoning_trace",
            "detect_contradictions",
        )
    },
    **{
        name: (court_output, name)
        for name in (
            "uses_accepted_evidence_ids",
            "reasoning_intro_for_label",
            "render_evidence_grounded_reasoning",
            "render_evidence_grounded_changelog",
            "is_generic_court_summary",
            "prefer_deterministic_explanation",
            "select_court_reasoning",
            "select_court_changelog",
            "should_skip_court_advisory",
            "build_skipped_court_advisory",
        )
    },
    "polish_explanation_with_model": (explanation_polish, "polish_explanation_with_model"),
    "should_run_explanation_polish": (explanation_polish, "should_run_explanation_polish"),
    "extract_polish_payload": (explanation_polish, "extract_polish_payload"),
    "validate_polish_payload": (explanation_polish, "validate_polish_payload"),
}


def resolve_compat(name: str) -> Any:
    if name in _MODULES:
        return _MODULES[name]
    source = _SOURCES.get(name) or _SOURCES.get(name.removeprefix("_"))
    if source is not None:
        module, attribute = source
        return getattr(module, attribute)
    raise AttributeError(name)
