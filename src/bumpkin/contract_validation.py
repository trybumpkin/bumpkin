from __future__ import annotations

from bumpkin.analysis import explanation_facts as explanation_dsl
from bumpkin.analysis.case_file import CASE_FILE_VERSION
from bumpkin.contract_validation_v5 import validate_v5_fields as _validate_v5_fields

COVERAGE_VERSION = "coverage_contract_v1"


def validate_base_fields(payload: dict[str, object]) -> list[str]:
    errors: list[str] = []
    contract_version = str(payload.get("output_contract_version", "")).strip()
    if contract_version not in {"v3", "v4", "v5"}:
        errors.append(f"Invalid output_contract_version: {contract_version!r}")

    required = (
        "output_contract_version",
        "status",
        "analysis_state",
        "classification_source",
        "reasoning",
        "planner",
        "coverage_contract",
    )
    errors.extend(f"Missing required output field: {key}" for key in required if key not in payload)

    status = str(payload.get("status", ""))
    if status not in {"classified", "manual_review"}:
        errors.append(f"Invalid status: {status!r}")

    analysis_state = str(payload.get("analysis_state", ""))
    if analysis_state not in {"authoritative", "degraded_fallback", "manual_review"}:
        errors.append(f"Invalid analysis_state: {analysis_state!r}")

    if len(str(payload.get("reasoning", "")).strip()) < 10:
        errors.append("Reasoning is too short for output contract.")
    return errors


def _validate_non_empty_string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        return [f"{field} must be a list of non-empty strings."]
    return []


def _validate_rows(value: object, field: str) -> list[str]:
    if not isinstance(value, list):
        return [f"{field} must be a list."]
    errors: list[str] = []
    required = ("path", "rule", "action", "target", "impact_scope", "suggested_bump", "severity")
    for index, row in enumerate(value):
        if not isinstance(row, dict):
            errors.append(f"{field}[{index}] must be an object.")
            continue
        errors.extend(
            f"{field}[{index}].{key} must be non-empty."
            for key in required
            if not str(row.get(key, "")).strip()
        )
    return errors


def _validate_case_file(payload: dict[str, object], errors: list[str]) -> None:
    case_file = payload.get("case_file")
    if not isinstance(case_file, dict):
        errors.append("v4/v5 payload must include case_file object.")
    elif str(case_file.get("version", "")).strip() != CASE_FILE_VERSION:
        errors.append(
            f"Invalid case_file.version: {str(case_file.get('version', '')).strip()!r} "
            f"(expected {CASE_FILE_VERSION!r})"
        )


def _validate_case_file_stats(payload: dict[str, object], errors: list[str]) -> None:
    case_file_stats = payload.get("case_file_stats")
    if not isinstance(case_file_stats, dict):
        errors.append("v4/v5 payload must include case_file_stats object.")
        return
    for key in ("token_budget", "estimated_input_tokens", "findings_included", "findings_omitted"):
        value = case_file_stats.get(key)
        if not isinstance(value, int) or value < 0:
            errors.append(f"case_file_stats.{key} must be a non-negative integer.")


def _validate_court_verdict(payload: dict[str, object], errors: list[str]) -> None:
    court_verdict = payload.get("court_verdict")
    if court_verdict is None:
        return
    if not isinstance(court_verdict, dict):
        errors.append("v4/v5 payload court_verdict must be an object when provided.")
        return
    for key in ("accepted_evidence_ids", "rejected_evidence_ids"):
        errors.extend(
            _validate_non_empty_string_list(court_verdict.get(key, []), f"court_verdict.{key}")
        )


def validate_advisory_fields(payload: dict[str, object], contract_version: str) -> list[str]:
    if contract_version not in {"v4", "v5"}:
        return []
    errors: list[str] = []
    decision_authority = str(payload.get("decision_authority", "")).strip()
    if decision_authority not in {"deterministic", "court"}:
        errors.append("v4/v5 payload must set decision_authority to deterministic or court.")
    for key in ("court_fallback_reason", "court_skipped_reason"):
        value = payload.get(key)
        if value is not None and not isinstance(value, str):
            errors.append(f"v4/v5 payload {key} must be a string.")
    if "deterministic_label" not in payload:
        errors.append("v4/v5 payload must include deterministic_label.")
    advisory_status = str(payload.get("advisory_status", "")).strip()
    if advisory_status not in {"aligned", "manual_review", "degraded", "skipped"}:
        errors.append(f"Invalid advisory_status: {advisory_status!r}")
    _validate_case_file(payload, errors)
    _validate_case_file_stats(payload, errors)
    _validate_court_verdict(payload, errors)
    errors.extend(_validate_rows(payload.get("explainability_rows"), "explainability_rows"))
    if contract_version == "v5":
        _validate_v5_fields(payload, errors)
    return errors


def validate_status_fields(payload: dict[str, object], contract_version: str) -> list[str]:
    status = str(payload.get("status", ""))
    errors: list[str] = []
    if status == "manual_review":
        errors.extend(
            f"Manual review payload must not include {key}."
            for key in ("label", "confidence", "changelog")
            if payload.get(key) is not None
        )
        return errors
    if status != "classified":
        return errors
    errors.extend(
        f"Classified payload must include non-empty {key}."
        for key in ("label", "confidence", "changelog")
        if not str(payload.get(key, "")).strip()
    )
    rows = payload.get("explainability_rows")
    if not isinstance(rows, list) or not rows:
        errors.append("Classified payload must include non-empty explainability_rows.")
    elif not explanation_dsl.filter_semantic_delta_rows(rows):
        errors.append(
            "Classified payload must include semantic explainability_rows; path-only rows are invalid."
        )
    if contract_version == "v5":
        semantic_facts = payload.get("semantic_facts")
        if not isinstance(semantic_facts, list) or not semantic_facts:
            errors.append("Classified v5 payload must include non-empty semantic_facts.")
        elif not explanation_dsl.filter_semantic_delta_rows(semantic_facts):
            errors.append("Classified v5 payload semantic_facts must be semantic rows.")
        proof_obligations = payload.get("proof_obligations")
        if isinstance(proof_obligations, dict):
            critical_missing = proof_obligations.get("critical_missing", [])
            if isinstance(critical_missing, list) and critical_missing:
                errors.append(
                    "Classified v5 payload must not include critical missing proof obligations."
                )
    return errors


def validate_planner_fields(payload: dict[str, object]) -> list[str]:
    planner = payload.get("planner")
    if not isinstance(planner, dict):
        return ["planner must be an object."]
    errors: list[str] = []
    if not str(planner.get("version", "")).strip():
        errors.append("planner.version is required.")
    route = str(planner.get("route", "")).strip()
    if route not in {"full", "chunked", "evidence_targeted", "manual_review"}:
        errors.append(f"Invalid planner.route: {route!r}")
    return errors


def validate_coverage_fields(payload: dict[str, object]) -> list[str]:
    coverage = payload.get("coverage_contract")
    if not isinstance(coverage, dict):
        return ["coverage_contract must be an object."]
    errors: list[str] = []
    version = str(coverage.get("version", "")).strip()
    if version != COVERAGE_VERSION:
        errors.append(
            f"Invalid coverage_contract.version: {version!r} (expected {COVERAGE_VERSION!r})"
        )
    status = str(coverage.get("status", "")).strip()
    if status not in {"pass", "fail"}:
        errors.append(f"Invalid coverage_contract.status: {status!r}")
    for key in ("critical_files_total", "critical_files_covered", "omitted_files_total"):
        value = coverage.get(key)
        if not isinstance(value, int) or value < 0:
            errors.append(f"coverage_contract.{key} must be a non-negative integer.")
    if not isinstance(coverage.get("omitted_critical_files"), list):
        errors.append("coverage_contract.omitted_critical_files must be a list.")
    return errors
