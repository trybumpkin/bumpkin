from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bumpkin.analysis.diffing import DiffResult
from bumpkin.orchestrator import adjudication as orchestrator_adjudication
from bumpkin.orchestrator import court_output as orchestrator_court_output
from bumpkin.orchestrator import explainability as orchestrator_explainability
from bumpkin.orchestrator import explanation_polish
from bumpkin.versioning.tags import detect_next_version


@dataclass(frozen=True)
class CourtAuthorityArtifacts:
    result: dict[str, Any]
    status: str
    classification_source: str
    analysis_state: str
    failure_category: str | None
    current_tag: str | None
    next_tag: str | None
    notes: list[str]


def apply_court_authority(
    *,
    decision_authority: str,
    court_advisory: dict[str, Any],
    case_file: dict[str, Any],
    pre_court_result: dict[str, Any],
    pre_court_status: str,
    deterministic_label: str | None,
    deterministic_next_tag: str | None,
    court_fallback_reason: str | None,
    court_model_used: str | None,
    advisory_token: str,
    endpoint: str,
    model: str,
    max_retries: int,
    request_timeout: int,
    diff_result: DiffResult,
    pre_1_0_breaking_as_minor: bool,
    result: dict[str, Any],
    status: str,
    classification_source: str,
    analysis_state: str,
    failure_category: str | None,
    current_tag: str | None,
    next_tag: str | None,
    notes: list[str],
) -> CourtAuthorityArtifacts:
    updated_result = dict(result)
    updated_status = status
    updated_classification_source = classification_source
    updated_analysis_state = analysis_state
    updated_failure_category = failure_category
    updated_current_tag = current_tag
    updated_next_tag = next_tag
    updated_notes = list(notes)

    if decision_authority != "court":
        return CourtAuthorityArtifacts(
            result=updated_result,
            status=updated_status,
            classification_source=updated_classification_source,
            analysis_state=updated_analysis_state,
            failure_category=updated_failure_category,
            current_tag=updated_current_tag,
            next_tag=updated_next_tag,
            notes=updated_notes,
        )

    advisory_status = str(court_advisory.get("status", "")).strip().lower()
    advisory_label = str(court_advisory.get("label", "")).strip().upper()
    if advisory_status in {"aligned", "manual_review"} and advisory_label in {
        "MAJOR",
        "MINOR",
        "PATCH",
        "NO_BUMP",
    }:
        evidence_lookup = orchestrator_explainability.case_file_evidence_lookup(case_file)
        using_accepted_evidence_ids = orchestrator_court_output.uses_accepted_evidence_ids(
            court_advisory=court_advisory,
            evidence_lookup=evidence_lookup,
        )
        selected_records = orchestrator_explainability.select_explanation_records(
            advisory_label=advisory_label,
            court_advisory=court_advisory,
            evidence_lookup=evidence_lookup,
            max_items=3,
        )
        selected_reasoning, used_evidence_reasoning = (
            orchestrator_court_output.render_evidence_grounded_reasoning(
                advisory_label=advisory_label,
                court_advisory=court_advisory,
                evidence_lookup=evidence_lookup,
            )
        )
        selected_changelog, used_evidence_changelog = (
            orchestrator_court_output.render_evidence_grounded_changelog(
                advisory_label=advisory_label,
                court_advisory=court_advisory,
                evidence_lookup=evidence_lookup,
            )
        )
        used_deterministic_reasoning = False
        used_deterministic_changelog = False
        if not selected_reasoning:
            selected_reasoning, used_deterministic_reasoning = (
                orchestrator_court_output.select_court_reasoning(
                    court_advisory=court_advisory,
                    advisory_label=advisory_label,
                    pre_court_result=pre_court_result,
                )
            )
        if not selected_changelog:
            selected_changelog, used_deterministic_changelog = (
                orchestrator_court_output.select_court_changelog(
                    advisory_label=advisory_label,
                    court_advisory=court_advisory,
                    pre_court_result=pre_court_result,
                )
            )
        polish_applied = False
        polish_failure_reason: str | None = None
        confidence_text = str(court_advisory.get("confidence", "low")).strip().lower() or "low"
        if explanation_polish.should_run_explanation_polish(
            reasoning=selected_reasoning,
            changelog=selected_changelog,
            confidence=confidence_text,
            token=advisory_token,
        ):
            polish_reasoning, polish_changelog, polish_applied, polish_failure_reason = (
                explanation_polish.polish_explanation_with_model(
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
            orchestrator_explainability.enforce_explicit_explanation(
                advisory_label=advisory_label,
                reasoning=selected_reasoning,
                changelog=selected_changelog,
                records=selected_records,
                fallback_paths=diff_result.analyzed_files,
            )
        )
        updated_result = {
            "status": "classified",
            "label": advisory_label,
            "confidence": confidence_text,
            "reasoning": selected_reasoning,
            "changelog": selected_changelog,
        }
        updated_status = "classified"
        updated_classification_source = "court"
        updated_analysis_state = "authoritative"
        updated_failure_category = None
        if used_deterministic_reasoning:
            updated_notes.append(
                "Court authority reused deterministic reasoning because court explanation was generic or low-confidence."
            )
        elif used_evidence_reasoning:
            if using_accepted_evidence_ids:
                updated_notes.append(
                    "Court authority generated reasoning from accepted evidence IDs."
                )
            else:
                updated_notes.append(
                    "Court authority generated reasoning from deterministic evidence fallback records."
                )
        if used_deterministic_changelog:
            updated_notes.append(
                "Court authority reused deterministic changelog because court explanation was generic or low-confidence."
            )
        elif used_evidence_changelog:
            if using_accepted_evidence_ids:
                updated_notes.append(
                    "Court authority generated changelog from accepted evidence IDs."
                )
            else:
                updated_notes.append(
                    "Court authority generated changelog from deterministic evidence fallback records."
                )
        if polish_applied:
            updated_notes.append("Applied low-token explanation polish pass for readability.")
        elif polish_failure_reason:
            updated_notes.append(
                f"Explanation polish skipped/failed; kept deterministic wording ({polish_failure_reason})."
            )
        if explicit_regenerated:
            updated_notes.append(
                "Explicitness gate regenerated reasoning/changelog to include concrete file anchors and action verbs."
            )
        if advisory_label != deterministic_label:
            updated_notes.append(
                f"Court authority applied: deterministic {deterministic_label} -> court {advisory_label}."
            )
        if advisory_label != "NO_BUMP":
            updated_current_tag, updated_next_tag, court_version_notes = detect_next_version(
                advisory_label,
                pre_1_0_breaking_as_minor=pre_1_0_breaking_as_minor,
            )
            updated_notes.extend(court_version_notes)
        else:
            updated_next_tag = None
    elif advisory_status in {"degraded", "skipped"} and pre_court_status == "classified":
        updated_result = pre_court_result
        updated_status = "classified"
        updated_classification_source = "deterministic-court-fallback"
        updated_analysis_state = (
            "degraded_fallback" if advisory_status == "degraded" else "authoritative"
        )
        if advisory_status == "degraded":
            updated_failure_category = (
                orchestrator_adjudication.categorize_failure_reason(court_fallback_reason)
                or updated_failure_category
            )
        updated_next_tag = deterministic_next_tag
        if advisory_status == "degraded":
            updated_notes.append(
                "Court authority degraded; using pre-court deterministic classification as fallback."
            )
        else:
            updated_notes.append(
                "Court authority skipped; using pre-court deterministic classification."
            )
    else:
        updated_result = {
            "status": "manual_review",
            "label": None,
            "confidence": None,
            "reasoning": (
                "Compatibility court is configured as final authority, but no reliable court verdict "
                "was available. Manual review is required."
            ),
            "changelog": None,
        }
        updated_status = "manual_review"
        updated_classification_source = "court-unavailable"
        updated_analysis_state = "manual_review"
        updated_next_tag = None
        updated_notes.append(
            "Court authority mode forced manual review because advisory status was not authoritative."
        )

    return CourtAuthorityArtifacts(
        result=updated_result,
        status=updated_status,
        classification_source=updated_classification_source,
        analysis_state=updated_analysis_state,
        failure_category=updated_failure_category,
        current_tag=updated_current_tag,
        next_tag=updated_next_tag,
        notes=updated_notes,
    )
