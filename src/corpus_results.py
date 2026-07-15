from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from corpus_labels import parse_expected_label_from_body
from corpus_models import ParsedPrediction, PRResultRow
from corpus_process import run_gh

RECOMMENDATION_LABEL_RE = re.compile(
    r"Recommendation\s*:\s*.*\b(MAJOR|MINOR|PATCH|NO_BUMP)\b", re.IGNORECASE
)
CONFIDENCE_RE = re.compile(r"Confidence\s*:\s*(high|medium|low)", re.IGNORECASE)
ANALYSIS_STATE_RE = re.compile(r"Analysis state:\s*([a-z_]+)\s*\(source=([^)]+)\)", re.IGNORECASE)
OVERRIDE_STATUS_RE = re.compile(r"Override\s*:\s*(.+)", re.IGNORECASE)
BUMPKIN_COMMENT_MARKER = "<!-- bumpkin:recommendation -->"


def _infer_mode_from_comment(*, lowered_body: str, analysis_state: str, source: str) -> str:
    if analysis_state == "degraded_fallback":
        if source == "semantic-fallback":
            return "fallback-heuristic"
        if source == "no-diff-heuristic":
            return "no-diff-heuristic"
        return "degraded_fallback"
    if "semantic fallback" in lowered_body:
        return "fallback-heuristic"
    if "stub mode" in lowered_body:
        return "stub"
    return "github-models"


def extract_bumpkin_prediction(comment_body: str) -> ParsedPrediction:
    lowered = (comment_body or "").lower()
    if BUMPKIN_COMMENT_MARKER not in lowered:
        return ParsedPrediction(
            "UNKNOWN", "unknown", "missing_comment", "unknown", "unknown", "unknown", False
        )
    analysis_match = ANALYSIS_STATE_RE.search(comment_body or "")
    analysis_state = analysis_match.group(1).strip().lower() if analysis_match else "unknown"
    classification_source = analysis_match.group(2).strip().lower() if analysis_match else "unknown"
    override_match = OVERRIDE_STATUS_RE.search(comment_body or "")
    override_status = override_match.group(1).strip() if override_match else "unknown"
    mode = _infer_mode_from_comment(
        lowered_body=lowered,
        analysis_state=analysis_state,
        source=classification_source,
    )
    if "manual review required" in lowered:
        return ParsedPrediction(
            "MANUAL_REVIEW",
            "none",
            mode,
            analysis_state,
            classification_source,
            override_status,
            override_status.lower().startswith("applied via "),
        )
    label_match = RECOMMENDATION_LABEL_RE.search(comment_body or "")
    confidence_match = CONFIDENCE_RE.search(comment_body or "")
    return ParsedPrediction(
        label=label_match.group(1).upper() if label_match else "UNKNOWN",
        confidence=confidence_match.group(1).lower() if confidence_match else "unknown",
        mode_used=mode,
        analysis_state=analysis_state,
        classification_source=classification_source,
        override_status=override_status,
        override_applied=override_status.lower().startswith("applied via "),
    )


def _find_latest_bumpkin_comment(comments: list[dict[str, Any]]) -> str:
    for comment in reversed(comments):
        body = str(comment.get("body", ""))
        if BUMPKIN_COMMENT_MARKER in body:
            return body
    return ""


def collect_results(*, repo: str, limit: int) -> list[PRResultRow]:
    prs = json.loads(
        run_gh(
            [
                "pr",
                "list",
                "--repo",
                repo,
                "--state",
                "merged",
                "--limit",
                str(limit),
                "--json",
                "number,url,body",
            ]
        )
    )
    rows: list[PRResultRow] = []
    for pr in prs:
        number = int(pr["number"])
        expected_label = parse_expected_label_from_body(str(pr.get("body", "")))
        comments = json.loads(run_gh(["api", f"repos/{repo}/issues/{number}/comments"]))
        prediction = extract_bumpkin_prediction(
            _find_latest_bumpkin_comment(comments if isinstance(comments, list) else [])
        )
        status = "matched" if expected_label == prediction.label else "mismatch"
        mismatch_type = (
            "none"
            if status == "matched"
            else ("forced_override" if prediction.override_applied else "natural")
        )
        rows.append(
            PRResultRow(
                pr_number=number,
                url=str(pr.get("url", "")),
                expected_label=expected_label,
                predicted_label=prediction.label,
                confidence=prediction.confidence,
                mode_used=prediction.mode_used,
                analysis_state=prediction.analysis_state,
                classification_source=prediction.classification_source,
                override_status=prediction.override_status,
                override_applied=prediction.override_applied,
                mismatch_type=mismatch_type,
                status=status,
            )
        )
    rows.sort(key=lambda row: row.pr_number)
    return rows


def write_results_tsv(path: Path, rows: list[PRResultRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "pr_number",
        "url",
        "expected_label",
        "predicted_label",
        "confidence",
        "mode_used",
        "analysis_state",
        "classification_source",
        "override_status",
        "override_applied",
        "mismatch_type",
        "status",
    ]
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(fields)
        for row in rows:
            writer.writerow(
                [getattr(row, field) for field in fields[:-3]]
                + [str(row.override_applied).lower(), row.mismatch_type, row.status]
            )


def summarize_rows(rows: list[PRResultRow]) -> dict[str, Any]:
    total = len(rows)
    matched = sum(row.status == "matched" for row in rows)
    mismatched = total - matched
    confusion: dict[str, dict[str, int]] = {}
    by_expected_label: dict[str, dict[str, float | int]] = {}
    for row in rows:
        bucket = confusion.setdefault(row.expected_label, {})
        bucket[row.predicted_label] = bucket.get(row.predicted_label, 0) + 1
        expected_bucket = by_expected_label.setdefault(
            row.expected_label, {"total": 0, "mismatched": 0, "disagreement_rate": 0.0}
        )
        expected_bucket["total"] += 1
        expected_bucket["mismatched"] += row.status != "matched"
    for bucket in by_expected_label.values():
        bucket["disagreement_rate"] = int(bucket["mismatched"]) / int(bucket["total"])
    degraded_rows = [row for row in rows if row.analysis_state == "degraded_fallback"]
    fallback_rows = [
        row
        for row in rows
        if row.classification_source in {"semantic-fallback", "no-diff-heuristic"}
    ]
    forced_override_mismatches = sum(
        row.status == "mismatch" and row.mismatch_type == "forced_override" for row in rows
    )
    natural_mismatches = sum(
        row.status == "mismatch" and row.mismatch_type == "natural" for row in rows
    )
    return {
        "total": total,
        "matched": matched,
        "mismatched": mismatched,
        "pass_rate": matched / total if total else 0.0,
        "disagreement_rate": mismatched / total if total else 0.0,
        "forced_override_mismatches": forced_override_mismatches,
        "natural_mismatches": natural_mismatches,
        "forced_override_mismatch_rate": forced_override_mismatches / mismatched
        if mismatched
        else 0.0,
        "by_expected_label": by_expected_label,
        "false_major_count": sum(
            row.predicted_label == "MAJOR" and row.expected_label != "MAJOR" for row in rows
        ),
        "false_minor_count": sum(
            row.predicted_label == "MINOR" and row.expected_label != "MINOR" for row in rows
        ),
        "degraded_fallback": _summarize_subset(degraded_rows),
        "fallback": _summarize_subset(fallback_rows),
        "confusion": confusion,
    }


def _summarize_subset(rows: list[PRResultRow]) -> dict[str, float | int]:
    mismatches = sum(row.status != "matched" for row in rows)
    return {
        "total": len(rows),
        "mismatches": mismatches,
        "mismatch_rate": mismatches / len(rows) if rows else 0.0,
    }
