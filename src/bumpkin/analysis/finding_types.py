from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SEVERITY_ORDER = {
    "NO_BUMP": 0,
    "PATCH": 1,
    "MINOR": 2,
    "MAJOR": 3,
}
CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}


@dataclass(frozen=True)
class Finding:
    id: str
    severity: str
    rule: str
    confidence: str
    title: str
    why: str
    evidence: list[dict[str, str]]
    suggested_bump: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "severity": self.severity,
            "rule": self.rule,
            "confidence": self.confidence,
            "title": self.title,
            "why": self.why,
            "evidence": self.evidence,
            "suggested_bump": self.suggested_bump,
        }


@dataclass(frozen=True)
class AggregatedFindingResult:
    status: str
    label: str | None
    confidence: str | None
    reasoning: str
    changelog: str | None
    aggregation_trace: str
    contributing_findings: int

    def to_result_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "label": self.label,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "changelog": self.changelog,
        }
