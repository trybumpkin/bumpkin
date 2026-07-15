from __future__ import annotations

import fnmatch
import re

from bumpkin.analysis.findings import Finding

from .boundaries import classify_finding_boundary

PYTHON_PUBLIC_EVIDENCE_RULES = {
    "python_api_module_import_binding_changed",
    "python_api_module_import_surface_changed",
    "python_api_module_local_surface_changed",
    "python_nested_constructor_changed",
    "python_constructor_ambiguous",
}
PYTHON_BREAKING_EVIDENCE_RULES = {
    "python_nested_constructor_changed",
    "python_constructor_ambiguous",
}


def _to_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def detect_behavior_contract_signals(
    analyzed_files: list[str],
    *,
    policy: str,
) -> dict[str, object]:
    summary: dict[str, object] = {
        "policy": policy,
        "enabled": policy != "off",
        "total": 0,
        "categories": {"openapi": 0, "schema": 0, "route_contract": 0},
        "sample_files": [],
    }
    if policy == "off":
        return summary

    openapi_patterns = (
        "**/openapi.json",
        "**/openapi.yaml",
        "**/openapi.yml",
        "**/swagger.json",
        "**/swagger.yaml",
        "**/swagger.yml",
    )
    schema_patterns = (
        "**/schema/**",
        "**/schemas/**",
        "**/*.schema.json",
        "**/*.schema.ts",
        "**/*.schema.js",
        "**/*-schema.ts",
        "**/*-schema.js",
    )
    route_contract_pattern = re.compile(
        r"(^|/)(routes?|api)/.+(contract|response|dto|schema)", re.IGNORECASE
    )
    matched: dict[str, set[str]] = {"openapi": set(), "schema": set(), "route_contract": set()}
    for raw in analyzed_files:
        path = raw.strip().replace("\\", "/").lstrip("./")
        lower = path.lower()
        if not lower:
            continue
        if any(fnmatch.fnmatch(lower, pattern) for pattern in openapi_patterns):
            matched["openapi"].add(path)
        if any(fnmatch.fnmatch(lower, pattern) for pattern in schema_patterns):
            matched["schema"].add(path)
        if route_contract_pattern.search(lower):
            matched["route_contract"].add(path)

    categories = {name: len(values) for name, values in matched.items()}
    all_files = sorted({item for values in matched.values() for item in values})
    summary["categories"] = categories
    summary["total"] = len(all_files)
    summary["sample_files"] = all_files[:6]
    return summary


def summarize_evidence(
    findings: list[Finding],
    *,
    public_hints: list[str],
    contract_signals: dict[str, object],
) -> dict[str, int]:
    export_public = 0
    export_breaking = 0
    unknown_impactful = 0
    for finding in findings:
        severity = finding.severity.upper()
        boundary = classify_finding_boundary(finding, public_hints=public_hints)
        if (
            severity in {"MINOR", "MAJOR"}
            or finding.rule in PYTHON_PUBLIC_EVIDENCE_RULES
            or finding.rule == "python_requires_floor_raised"
        ) and boundary == "unknown":
            unknown_impactful += 1
        if (
            finding.rule == "python_requires_floor_raised"
            or finding.rule in PYTHON_PUBLIC_EVIDENCE_RULES
        ):
            if boundary != "public":
                continue
        elif not finding.rule.startswith("export_"):
            continue
        if boundary == "internal":
            continue
        if severity in {"MINOR", "MAJOR"} or finding.rule in PYTHON_PUBLIC_EVIDENCE_RULES:
            export_public += 1
        if severity == "MAJOR" or finding.rule in PYTHON_BREAKING_EVIDENCE_RULES:
            export_breaking += 1

    contract_public = _to_int(contract_signals.get("total", 0), default=0)
    return {
        "export_public_evidence": export_public,
        "export_breaking_evidence": export_breaking,
        "behavior_contract_evidence": contract_public,
        "strong_public_evidence": export_public + contract_public,
        "strong_breaking_evidence": export_breaking,
        "unknown_impactful_findings": unknown_impactful,
    }
