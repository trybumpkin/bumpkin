from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bumpkin.analysis.case_file import build_case_file, render_case_file_text
from bumpkin.orchestrator import court as orchestrator_court
from bumpkin.orchestrator import court_output as orchestrator_court_output


@dataclass(frozen=True)
class CourtSetupArtifacts:
    case_file: dict[str, Any]
    case_file_stats: dict[str, Any]
    pre_court_result: dict[str, Any]
    pre_court_status: str
    deterministic_label: str | None
    deterministic_confidence: str | None
    deterministic_next_tag: str | None
    advisory_token: str
    court_advisory: dict[str, Any]
    court_fallback_reason: str | None
    court_model_used: str | None
    court_skipped_reason: str | None
    notes: list[str]


def prepare_court_setup(
    *,
    result: dict[str, Any],
    findings: list[Any],
    evidence_items: list[Any],
    policy_effects: list[str],
    notes: list[str],
    coverage_contract: dict[str, Any],
    boundary_summary: dict[str, int],
    evidence_summary: dict[str, int],
    allow_model_call: bool,
    token: str,
    mode: str,
    model: str,
    fallback_model: str | None,
    endpoint: str,
    max_retries: int,
    request_timeout: int,
    language_hints: list[str] | None,
    classification_source: str,
    mode_used: str,
    next_tag: str | None,
) -> CourtSetupArtifacts:
    updated_notes = list(notes)

    case_file_build = build_case_file(
        engine_result=result,
        findings=findings,
        evidence_items=evidence_items,
        policy_effects=policy_effects,
        notes=updated_notes,
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
    advisory_token = token if allow_model_call else ""

    should_skip_court, court_skipped_reason = orchestrator_court_output.should_skip_court_advisory(
        status=pre_court_status,
        deterministic_label=deterministic_label,
        deterministic_confidence=deterministic_confidence,
        mode_used=mode_used,
        classification_source=classification_source,
    )
    if should_skip_court and court_skipped_reason:
        court_advisory = orchestrator_court_output.build_skipped_court_advisory(
            deterministic_label=deterministic_label,
            deterministic_confidence=deterministic_confidence,
            court_skipped_reason=court_skipped_reason,
        )
        court_fallback_reason = None
        court_model_used = None
        updated_notes.append(f"Court advisory skipped: {court_skipped_reason}.")
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
        updated_notes.append(f"Compatibility court analyzed by model: {court_model_used}.")
    if court_fallback_reason:
        updated_notes.append(f"Compatibility court advisory degraded: {court_fallback_reason}.")
    if str(court_advisory.get("status", "")).lower() == "manual_review":
        reason = str(court_advisory.get("disagreement_reason", "")).strip()
        if reason:
            updated_notes.append(reason)

    return CourtSetupArtifacts(
        case_file=case_file,
        case_file_stats=case_file_stats,
        pre_court_result=pre_court_result,
        pre_court_status=pre_court_status,
        deterministic_label=deterministic_label,
        deterministic_confidence=deterministic_confidence,
        deterministic_next_tag=deterministic_next_tag,
        advisory_token=advisory_token,
        court_advisory=court_advisory,
        court_fallback_reason=court_fallback_reason,
        court_model_used=court_model_used,
        court_skipped_reason=court_skipped_reason,
        notes=updated_notes,
    )
