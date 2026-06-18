from __future__ import annotations

from dataclasses import dataclass

from bumpkin.analysis.diffing import DiffResult
from bumpkin.analysis.findings import Finding, aggregate_findings
from bumpkin.orchestrator import adjudication as orchestrator_adjudication
from bumpkin.providers.llm import get_no_bump_recommendation, get_stub_recommendation
from bumpkin.providers.semantic import semantic_fallback_recommendation


@dataclass(frozen=True)
class BaseClassificationArtifacts:
    result: dict[str, object]
    aggregation_trace: str | None
    fallback_reason: str | None
    mode_used: str
    model_used: str | None
    classification_source: str
    notes: list[str]


def determine_base_classification(
    *,
    diff_result: DiffResult,
    findings: list[Finding],
    mode: str,
    scope_mismatch_detected: bool,
    scope_mismatch_reason: str | None,
    surface_area_hints: list[str],
    notes: list[str],
) -> BaseClassificationArtifacts:
    local_notes = list(notes)
    fallback_reason: str | None = None
    mode_used = "deterministic-engine"
    model_used: str | None = None
    classification_source = "deterministic-engine"
    aggregation_trace: str | None = None

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
                surface_area_hints=surface_area_hints,
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

    return BaseClassificationArtifacts(
        result=result,
        aggregation_trace=aggregation_trace,
        fallback_reason=fallback_reason,
        mode_used=mode_used,
        model_used=model_used,
        classification_source=classification_source,
        notes=local_notes,
    )
