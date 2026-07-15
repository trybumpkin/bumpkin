from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CommitCandidate:
    sha: str
    subject: str
    files: list[str]
    expected_label: str
    category: str


@dataclass
class PRResultRow:
    pr_number: int
    url: str
    expected_label: str
    predicted_label: str
    confidence: str
    mode_used: str
    analysis_state: str
    classification_source: str
    override_status: str
    override_applied: bool
    mismatch_type: str
    status: str


@dataclass
class ParsedPrediction:
    label: str
    confidence: str
    mode_used: str
    analysis_state: str
    classification_source: str
    override_status: str
    override_applied: bool


def row_to_dict(row: PRResultRow) -> dict[str, Any]:
    return {
        "pr_number": row.pr_number,
        "url": row.url,
        "expected_label": row.expected_label,
        "predicted_label": row.predicted_label,
        "confidence": row.confidence,
        "mode_used": row.mode_used,
        "analysis_state": row.analysis_state,
        "classification_source": row.classification_source,
        "override_status": row.override_status,
        "override_applied": row.override_applied,
        "mismatch_type": row.mismatch_type,
        "status": row.status,
    }
