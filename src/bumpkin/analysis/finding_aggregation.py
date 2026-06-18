from __future__ import annotations

from bumpkin.analysis.finding_types import (
    CONFIDENCE_ORDER,
    AggregatedFindingResult,
    Finding,
)


def _confidence_for_findings(findings: list[Finding], severity: str) -> str:
    ranked = [
        CONFIDENCE_ORDER.get(finding.confidence, 0)
        for finding in findings
        if finding.severity == severity
    ]
    if not ranked:
        return "low"
    # Conservative confidence: one weak contributing finding lowers confidence.
    min_rank = min(ranked)
    for label, rank in CONFIDENCE_ORDER.items():
        if rank == min_rank:
            return label
    return "low"


def _summary_counts(findings: list[Finding]) -> str:
    counts = {"MAJOR": 0, "MINOR": 0, "PATCH": 0, "NO_BUMP": 0, "MANUAL_REVIEW": 0}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    return (
        f"MAJOR={counts['MAJOR']}, MINOR={counts['MINOR']}, PATCH={counts['PATCH']}, "
        f"NO_BUMP={counts['NO_BUMP']}, MANUAL_REVIEW={counts['MANUAL_REVIEW']}"
    )


def aggregate_findings(findings: list[Finding]) -> AggregatedFindingResult | None:
    if not findings:
        return None

    severities = {finding.severity for finding in findings}
    counts_text = _summary_counts(findings)

    if "MAJOR" in severities:
        label = "MAJOR"
        trace = "MAJOR findings present; selected MAJOR."
    elif "MINOR" in severities:
        label = "MINOR"
        trace = "No MAJOR findings; MINOR findings present; selected MINOR."
    elif "PATCH" in severities:
        label = "PATCH"
        trace = "No MAJOR/MINOR findings; PATCH findings present; selected PATCH."
    elif "NO_BUMP" in severities:
        label = "NO_BUMP"
        trace = "Only NO_BUMP findings present; selected NO_BUMP."
    else:
        return AggregatedFindingResult(
            status="manual_review",
            label=None,
            confidence=None,
            reasoning=(
                "Deterministic findings could not produce an authoritative SemVer bump. "
                f"Finding counts: {counts_text}."
            ),
            changelog=None,
            aggregation_trace="No deterministic bump severity found; manual review required.",
            contributing_findings=len(findings),
        )

    changelog = {
        "MAJOR": "feat: introduce breaking api changes",
        "MINOR": "feat: add backward-compatible api changes",
        "PATCH": "fix: update internal implementation",
        "NO_BUMP": "chore: no release required",
    }[label]
    confidence = _confidence_for_findings(findings, label)
    return AggregatedFindingResult(
        status="classified",
        label=label,
        confidence=confidence,
        reasoning=(
            f"Deterministic exported API analysis produced findings with counts: {counts_text}."
        ),
        changelog=changelog,
        aggregation_trace=trace,
        contributing_findings=len(findings),
    )
