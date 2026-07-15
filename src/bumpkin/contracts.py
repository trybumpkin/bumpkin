from __future__ import annotations

import fnmatch
from collections.abc import Iterable

from bumpkin.contract_validation import (
    validate_advisory_fields,
    validate_base_fields,
    validate_coverage_fields,
    validate_planner_fields,
    validate_status_fields,
)

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
    contract_version = str(payload.get("output_contract_version", "")).strip()
    errors = validate_base_fields(payload)
    errors.extend(validate_advisory_fields(payload, contract_version))
    errors.extend(validate_status_fields(payload, contract_version))
    errors.extend(validate_planner_fields(payload))
    errors.extend(validate_coverage_fields(payload))
    return errors
