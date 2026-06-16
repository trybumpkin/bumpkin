from __future__ import annotations

import fnmatch
from collections.abc import Iterable

from bumpkin.analysis import explanation_facts as explanation_dsl
from bumpkin.analysis.case_file import CASE_FILE_VERSION

COVERAGE_VERSION = "coverage_contract_v1"


def _normalize(path: str) -> str:
    normalized = str(path or "").strip().replace("\\", "/")
    normalized = normalized.removeprefix("./")
    return normalized.lstrip("/")


def _matches_any(path: str, patterns: Iterable[str]) -> bool:
    normalized = _normalize(path)
    if not normalized:
        return False
    for raw in patterns:
        pattern = _normalize(str(raw))
        if not pattern:
            continue
        if fnmatch.fnmatch(normalized, pattern):
            return True
        stem = pattern.replace("**", "").rstrip("/")
        if stem and normalized.startswith(stem):
            return True
    return False


def build_coverage_contract(
    *,
    analyzed_files: list[str],
    chunking_meta: dict[str, object] | None,
    public_api_hints: list[str],
    behavior_contract_signals: dict[str, object] | None,
) -> dict[str, object]:
    analyzed = {_normalize(path) for path in analyzed_files if _normalize(path)}
    raw_omitted = (chunking_meta or {}).get("omitted_files", [])
    omitted_items = raw_omitted if isinstance(raw_omitted, list) else []
    omitted = {_normalize(path) for path in omitted_items if _normalize(path)}

    critical_files: set[str] = {path for path in analyzed if _matches_any(path, public_api_hints)}
    sample_files = []
    if isinstance(behavior_contract_signals, dict):
        raw_sample = behavior_contract_signals.get("sample_files", [])
        if isinstance(raw_sample, list):
            sample_files = [str(item) for item in raw_sample if str(item).strip()]
    critical_files.update({_normalize(path) for path in sample_files if _normalize(path)})
    critical_files &= analyzed

    covered = critical_files - omitted
    omitted_critical = sorted(critical_files - covered)
    status = "pass" if not omitted_critical else "fail"
    return {
        "version": COVERAGE_VERSION,
        "status": status,
        "critical_files_total": len(critical_files),
        "critical_files_covered": len(covered),
        "omitted_critical_files": omitted_critical,
        "omitted_files_total": len(omitted),
    }


def validate_output_contract(payload: dict[str, object]) -> list[str]:
    errors: list[str] = []
    contract_version = str(payload.get("output_contract_version", "")).strip()
    if contract_version not in {"v3", "v4", "v5"}:
        errors.append(f"Invalid output_contract_version: {contract_version!r}")

    required = [
        "output_contract_version",
        "status",
        "analysis_state",
        "classification_source",
        "reasoning",
        "planner",
        "coverage_contract",
    ]
    errors.extend(
        [f"Missing required output field: {key}" for key in required if key not in payload]
    )

    status = str(payload.get("status", ""))
    if status not in {"classified", "manual_review"}:
        errors.append(f"Invalid status: {status!r}")

    analysis_state = str(payload.get("analysis_state", ""))
    if analysis_state not in {"authoritative", "degraded_fallback", "manual_review"}:
        errors.append(f"Invalid analysis_state: {analysis_state!r}")

    reasoning = str(payload.get("reasoning", "")).strip()
    if len(reasoning) < 10:
        errors.append("Reasoning is too short for output contract.")

    if contract_version in {"v4", "v5"}:
        decision_authority = str(payload.get("decision_authority", "")).strip()
        if decision_authority not in {"deterministic", "court"}:
            errors.append("v4/v5 payload must set decision_authority to deterministic or court.")
        court_fallback_reason = payload.get("court_fallback_reason")
        if court_fallback_reason is not None and not isinstance(court_fallback_reason, str):
            errors.append("v4/v5 payload court_fallback_reason must be a string.")
        court_skipped_reason = payload.get("court_skipped_reason")
        if court_skipped_reason is not None and not isinstance(court_skipped_reason, str):
            errors.append("v4/v5 payload court_skipped_reason must be a string.")
        if "deterministic_label" not in payload:
            errors.append("v4/v5 payload must include deterministic_label.")
        advisory_status = str(payload.get("advisory_status", "")).strip()
        if advisory_status not in {"aligned", "manual_review", "degraded", "skipped"}:
            errors.append(f"Invalid advisory_status: {advisory_status!r}")
        case_file = payload.get("case_file")
        if not isinstance(case_file, dict):
            errors.append("v4/v5 payload must include case_file object.")
        else:
            case_file_version = str(case_file.get("version", "")).strip()
            if case_file_version != CASE_FILE_VERSION:
                errors.append(
                    f"Invalid case_file.version: {case_file_version!r} (expected {CASE_FILE_VERSION!r})"
                )
        case_file_stats = payload.get("case_file_stats")
        if not isinstance(case_file_stats, dict):
            errors.append("v4/v5 payload must include case_file_stats object.")
        else:
            for key in (
                "token_budget",
                "estimated_input_tokens",
                "findings_included",
                "findings_omitted",
            ):
                value = case_file_stats.get(key)
                if not isinstance(value, int) or value < 0:
                    errors.append(f"case_file_stats.{key} must be a non-negative integer.")
        court_verdict = payload.get("court_verdict")
        if court_verdict is not None:
            if not isinstance(court_verdict, dict):
                errors.append("v4/v5 payload court_verdict must be an object when provided.")
            else:
                for key in ("accepted_evidence_ids", "rejected_evidence_ids"):
                    value = court_verdict.get(key, [])
                    if not isinstance(value, list) or not all(
                        isinstance(item, str) and item.strip() for item in value
                    ):
                        errors.append(f"court_verdict.{key} must be a list of non-empty strings.")
        explainability_rows = payload.get("explainability_rows")
        if not isinstance(explainability_rows, list):
            errors.append("v4/v5 payload must include explainability_rows list.")
        else:
            for index, row in enumerate(explainability_rows):
                if not isinstance(row, dict):
                    errors.append(f"explainability_rows[{index}] must be an object.")
                    continue
                for key in (
                    "path",
                    "rule",
                    "action",
                    "target",
                    "impact_scope",
                    "suggested_bump",
                    "severity",
                ):
                    value = str(row.get(key, "")).strip()
                    if not value:
                        errors.append(f"explainability_rows[{index}].{key} must be non-empty.")
        if contract_version == "v5":
            semantic_facts = payload.get("semantic_facts")
            if not isinstance(semantic_facts, list):
                errors.append("v5 payload must include semantic_facts list.")
            else:
                for index, row in enumerate(semantic_facts):
                    if not isinstance(row, dict):
                        errors.append(f"semantic_facts[{index}] must be an object.")
                        continue
                    for key in (
                        "path",
                        "rule",
                        "action",
                        "target",
                        "impact_scope",
                        "suggested_bump",
                        "severity",
                    ):
                        value = str(row.get(key, "")).strip()
                        if not value:
                            errors.append(f"semantic_facts[{index}].{key} must be non-empty.")
            proof_obligations = payload.get("proof_obligations")
            if not isinstance(proof_obligations, dict):
                errors.append("v5 payload must include proof_obligations object.")
            else:
                version = str(proof_obligations.get("version", "")).strip()
                if version != "proof_obligations_v1":
                    errors.append(
                        f"Invalid proof_obligations.version: {version!r} (expected 'proof_obligations_v1')"
                    )
                for key in ("required", "satisfied", "missing", "critical_missing"):
                    value = proof_obligations.get(key)
                    if not isinstance(value, list) or not all(
                        isinstance(item, str) and item.strip() for item in value
                    ):
                        errors.append(
                            f"proof_obligations.{key} must be a list of non-empty strings."
                        )
            reasoning_trace = payload.get("reasoning_trace")
            if not isinstance(reasoning_trace, list):
                errors.append("v5 payload must include reasoning_trace list.")
            else:
                for index, claim in enumerate(reasoning_trace):
                    if not isinstance(claim, dict):
                        errors.append(f"reasoning_trace[{index}] must be an object.")
                        continue
                    evidence = claim.get("evidence")
                    policy = claim.get("policy")
                    impact = claim.get("impact")
                    if not isinstance(evidence, dict):
                        errors.append(f"reasoning_trace[{index}].evidence must be an object.")
                    else:
                        path = str(evidence.get("path", "")).strip()
                        evidence_id = str(evidence.get("evidence_id", "")).strip()
                        if not path and not evidence_id:
                            errors.append(
                                f"reasoning_trace[{index}].evidence requires non-empty path or evidence_id."
                            )
                    if not isinstance(policy, dict):
                        errors.append(f"reasoning_trace[{index}].policy must be an object.")
                    elif not str(policy.get("id", "")).strip():
                        errors.append(f"reasoning_trace[{index}].policy.id must be non-empty.")
                    if not isinstance(impact, dict):
                        errors.append(f"reasoning_trace[{index}].impact must be an object.")
                    else:
                        if not str(impact.get("statement", "")).strip():
                            errors.append(
                                f"reasoning_trace[{index}].impact.statement must be non-empty."
                            )
                        if not str(impact.get("implied_bump", "")).strip():
                            errors.append(
                                f"reasoning_trace[{index}].impact.implied_bump must be non-empty."
                            )
            contradictions = payload.get("contradictions")
            if not isinstance(contradictions, list):
                errors.append("v5 payload must include contradictions list.")
            else:
                for index, contradiction in enumerate(contradictions):
                    if not isinstance(contradiction, dict):
                        errors.append(f"contradictions[{index}] must be an object.")
                        continue
                    if not str(contradiction.get("code", "")).strip():
                        errors.append(f"contradictions[{index}].code must be non-empty.")
                    if not str(contradiction.get("message", "")).strip():
                        errors.append(f"contradictions[{index}].message must be non-empty.")
                    evidence_paths = contradiction.get("evidence_paths", [])
                    if not isinstance(evidence_paths, list) or not all(
                        isinstance(item, str) and item.strip() for item in evidence_paths
                    ):
                        errors.append(
                            f"contradictions[{index}].evidence_paths must be a list of non-empty strings."
                        )

    if status == "manual_review":
        if payload.get("label") is not None:
            errors.append("Manual review payload must not include label.")
        if payload.get("confidence") is not None:
            errors.append("Manual review payload must not include confidence.")
        if payload.get("changelog") is not None:
            errors.append("Manual review payload must not include changelog.")
    elif status == "classified":
        if str(payload.get("label", "")).strip() == "":
            errors.append("Classified payload must include non-empty label.")
        if str(payload.get("confidence", "")).strip() == "":
            errors.append("Classified payload must include non-empty confidence.")
        if str(payload.get("changelog", "")).strip() == "":
            errors.append("Classified payload must include non-empty changelog.")
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

    planner = payload.get("planner")
    if not isinstance(planner, dict):
        errors.append("planner must be an object.")
    else:
        if str(planner.get("version", "")).strip() == "":
            errors.append("planner.version is required.")
        route = str(planner.get("route", "")).strip()
        if route not in {"full", "chunked", "evidence_targeted", "manual_review"}:
            errors.append(f"Invalid planner.route: {route!r}")

    coverage = payload.get("coverage_contract")
    if not isinstance(coverage, dict):
        errors.append("coverage_contract must be an object.")
    else:
        version = str(coverage.get("version", "")).strip()
        if version != COVERAGE_VERSION:
            errors.append(
                f"Invalid coverage_contract.version: {version!r} (expected {COVERAGE_VERSION!r})"
            )
        coverage_status = str(coverage.get("status", "")).strip()
        if coverage_status not in {"pass", "fail"}:
            errors.append(f"Invalid coverage_contract.status: {coverage_status!r}")
        for number_key in ("critical_files_total", "critical_files_covered", "omitted_files_total"):
            value = coverage.get(number_key)
            if not isinstance(value, int) or value < 0:
                errors.append(f"coverage_contract.{number_key} must be a non-negative integer.")
        omitted_critical_files = coverage.get("omitted_critical_files")
        if not isinstance(omitted_critical_files, list):
            errors.append("coverage_contract.omitted_critical_files must be a list.")
    return errors
