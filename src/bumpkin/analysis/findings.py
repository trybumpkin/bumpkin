from __future__ import annotations

import re
from dataclasses import replace

from bumpkin.analysis import (
    finding_aggregation,
    finding_diff,
    finding_js_ts,
    finding_python_detection_context,
    finding_python_detector,
    finding_python_parameter_compat,
    finding_types,
    finding_workspace,
)

aggregate_findings = finding_aggregation.aggregate_findings
AggregatedFindingResult = finding_types.AggregatedFindingResult
CONFIDENCE_ORDER = finding_types.CONFIDENCE_ORDER
DIFF_GIT_HEADER = finding_diff.DIFF_GIT_HEADER
Finding = finding_types.Finding
SEVERITY_ORDER = finding_types.SEVERITY_ORDER
WorkspaceLoader = finding_workspace.WorkspaceLoader
build_filesystem_workspace_loader = finding_workspace.build_filesystem_workspace_loader
JS_TS_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts")
PYTHON_EXTENSIONS = finding_python_detection_context.PYTHON_EXTENSIONS


def _reindex_findings(findings: list[Finding]) -> list[Finding]:
    return [
        replace(finding, id=f"{finding.rule}:{index}") for index, finding in enumerate(findings, 1)
    ]


def _normalize_type(raw_type: str | None) -> str | None:
    if raw_type is None:
        return None
    cleaned = re.sub(r"\s+", " ", raw_type).strip()
    return cleaned or None


def _build_finding(
    *,
    severity: str,
    rule: str,
    confidence: str,
    title: str,
    why: str,
    path: str,
    snippet: str,
    counter: int,
) -> Finding:
    suggested = severity if severity != "MANUAL_REVIEW" else None
    return Finding(
        id=f"{rule}:{counter}",
        severity=severity,
        rule=rule,
        confidence=confidence,
        title=title,
        why=why,
        evidence=[{"path": path, "snippet": snippet[:180]}],
        suggested_bump=suggested,
    )


def detect_js_ts_export_findings(diff_text: str) -> list[Finding]:
    return finding_js_ts.run_js_ts_export_detection(
        diff_text,
        build_finding=_build_finding,
        normalize_type=_normalize_type,
        is_optional_widening=finding_python_parameter_compat.is_optional_widening,
        is_requiredness_tightening=finding_python_parameter_compat.is_requiredness_tightening,
    )


def detect_python_api_findings(
    diff_text: str,
    *,
    workspace_loader: WorkspaceLoader | None = None,
) -> list[Finding]:
    return finding_python_detector.run_python_api_detection(
        diff_text,
        workspace_loader=workspace_loader,
        build_finding=_build_finding,
    )


def detect_semver_findings(
    diff_text: str,
    *,
    workspace_loader: WorkspaceLoader | None = None,
) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(detect_js_ts_export_findings(diff_text))
    findings.extend(
        detect_python_api_findings(
            diff_text,
            workspace_loader=workspace_loader,
        )
    )
    return _reindex_findings(findings)
