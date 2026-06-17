from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bumpkin.analysis import explanation_facts as explanation_dsl
from bumpkin.analysis import semantic_review
from bumpkin.analysis.diffing import DiffResult
from bumpkin.orchestrator import explainability as orchestrator_explainability


@dataclass(frozen=True)
class SemanticTraceArtifacts:
    result: dict[str, Any]
    status: str
    classification_source: str
    analysis_state: str
    failure_category: str | None
    next_tag: str | None
    notes: list[str]
    decision_trace: dict[str, Any]
    explainability_rows: list[dict[str, str]]
    semantic_facts: list[dict[str, str]]
    proof_obligations: dict[str, Any]
    reasoning_trace: list[dict[str, Any]]
    contradictions: list[dict[str, Any]]


def build_semantic_trace_artifacts(
    *,
    result: dict[str, Any],
    status: str,
    court_advisory: dict[str, Any],
    case_file: dict[str, Any],
    diff_result: DiffResult,
    event_labels: list[str],
    policy_effects: list[str],
    decision_trace: dict[str, Any],
    classification_source: str,
    analysis_state: str,
    failure_category: str | None,
    next_tag: str | None,
    notes: list[str],
    deterministic_label: str | None,
    court_skipped_reason: str | None,
) -> SemanticTraceArtifacts:
    updated_result = dict(result)
    updated_status = status
    updated_notes = list(notes)
    updated_decision_trace = dict(decision_trace)
    updated_classification_source = classification_source
    updated_analysis_state = analysis_state
    updated_failure_category = failure_category
    updated_next_tag = next_tag

    explainability_rows: list[dict[str, str]] = []
    if updated_status == "classified":
        final_label = str(updated_result.get("label", "")).strip().upper()
        evidence_lookup_for_rows = orchestrator_explainability.case_file_evidence_lookup(case_file)
        explainability_rows = orchestrator_explainability.build_explainability_rows(
            advisory_label=final_label,
            court_advisory=court_advisory,
            evidence_lookup=evidence_lookup_for_rows,
            analyzed_files=diff_result.analyzed_files,
            diff_text=diff_result.full_diff_text,
            max_items=8,
        )
        semantic_rows = explanation_dsl.filter_semantic_delta_rows(explainability_rows)
        if not semantic_rows:
            updated_result = {
                "status": "manual_review",
                "label": None,
                "confidence": None,
                "reasoning": (
                    "Explainability contract is unsatisfied because deterministic DSL "
                    "did not emit semantic delta rows. Manual review is required."
                ),
                "changelog": None,
            }
            updated_status = "manual_review"
            updated_classification_source = "explainability-contract"
            updated_analysis_state = "manual_review"
            updated_failure_category = "explainability_semantic_contract_unsatisfied"
            updated_next_tag = None
            explainability_rows = []
            updated_notes.append(
                "Fail-closed explainability gate triggered: only path-level or empty explainability rows were available."
            )
        else:
            explainability_rows = semantic_rows

    semantic_facts = explanation_dsl.filter_semantic_delta_rows(explainability_rows)
    evaluated_label_for_obligations = (
        str(updated_result.get("label", "")).strip().upper()
        if updated_status == "classified"
        else (str(court_advisory.get("label", "")).strip().upper() or deterministic_label)
    )
    proof_obligations = semantic_review.evaluate_proof_obligations(
        status=updated_status,
        evaluated_label=evaluated_label_for_obligations,
        semantic_facts=semantic_facts,
    )
    critical_missing_obligations = semantic_review.critical_missing_proof_obligations(
        proof_obligations
    )
    if updated_status == "classified" and critical_missing_obligations:
        updated_result = {
            "status": "manual_review",
            "label": None,
            "confidence": None,
            "reasoning": (
                "Proof-obligation contract is unsatisfied because critical obligations are missing "
                f"({', '.join(critical_missing_obligations)}). Manual review is required."
            ),
            "changelog": None,
        }
        updated_status = "manual_review"
        updated_classification_source = "proof-obligation-contract"
        updated_analysis_state = "manual_review"
        updated_failure_category = (
            updated_failure_category or "proof_obligation_contract_unsatisfied"
        )
        updated_next_tag = None
        updated_notes.append(
            "Fail-closed proof-obligation gate triggered: classified output downgraded to manual_review."
        )
    proof_obligations["status"] = updated_status
    final_label_for_trace = (
        str(updated_result.get("label", "")).strip().upper()
        if updated_status == "classified"
        else None
    )
    contradictions = semantic_review.detect_contradictions(
        event_labels=event_labels,
        semantic_facts=semantic_facts,
        status=updated_status,
        final_label=final_label_for_trace,
    )
    semantic_facts = semantic_review.prioritize_semantic_facts(
        semantic_facts,
        contradiction_paths=semantic_review.extract_contradiction_paths(contradictions),
        max_items=8,
    )
    if updated_status == "classified":
        explainability_rows = list(semantic_facts)
    reasoning_trace = semantic_review.build_reasoning_trace(
        semantic_facts=semantic_facts,
        policy_effects=policy_effects,
        contradictions=contradictions,
        final_label=final_label_for_trace,
    )

    updated_decision_trace["decision_authority"] = updated_decision_trace.get("decision_authority")
    updated_decision_trace["deterministic_label"] = deterministic_label
    updated_decision_trace["court_skipped_reason"] = court_skipped_reason
    updated_decision_trace["explainability_rows"] = len(explainability_rows)
    updated_decision_trace["court"] = {
        "status": court_advisory.get("status"),
        "label": court_advisory.get("label"),
        "confidence": court_advisory.get("confidence"),
    }
    updated_decision_trace["proof_obligations_missing"] = len(proof_obligations.get("missing", []))
    updated_decision_trace["reasoning_trace_claims"] = len(reasoning_trace)
    updated_decision_trace["contradiction_count"] = len(contradictions)

    return SemanticTraceArtifacts(
        result=updated_result,
        status=updated_status,
        classification_source=updated_classification_source,
        analysis_state=updated_analysis_state,
        failure_category=updated_failure_category,
        next_tag=updated_next_tag,
        notes=updated_notes,
        decision_trace=updated_decision_trace,
        explainability_rows=explainability_rows,
        semantic_facts=semantic_facts,
        proof_obligations=proof_obligations,
        reasoning_trace=reasoning_trace,
        contradictions=contradictions,
    )
