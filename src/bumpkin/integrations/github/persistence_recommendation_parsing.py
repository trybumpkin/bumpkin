from __future__ import annotations

import re
from typing import Any

PROPOSED_BUMP_RE = re.compile(r"(?im)^proposed bump \(court\):\s*(?P<label>[A-Z_]+)")
RECOMMENDATION_LINE_RE = re.compile(
    r"(?im)^recommendation\s*:\s*[^\n\rA-Z]*(?P<label>NO[\s_-]?BUMP|MAJOR|MINOR|PATCH)\b"
)
VALID_BUMP_LABELS = frozenset({"MAJOR", "MINOR", "PATCH", "NO_BUMP"})
NEXT_VERSION_ARROW_RE = re.compile(
    "(?im)^next version\\s*:\\s*(?P<current>v?\\d+\\.\\d+\\.\\d+)\\s*(?:\\u2192|->)\\s*(?P<next>v?\\d+\\.\\d+\\.\\d+)\\s*$"
)
NEXT_VERSION_CURRENT_ONLY_RE = re.compile(
    r"(?im)^next version\s*:\s*not computed\s*\(current=(?P<current>v?\d+\.\d+\.\d+)\)\s*$"
)


def extract_comment_body(payload: dict[str, Any]) -> str:
    comment = payload.get("comment")
    if not isinstance(comment, dict):
        return ""
    body = comment.get("body")
    return str(body).strip() if body is not None else ""


def extract_recommended_label(comment_body: str) -> str | None:
    match = PROPOSED_BUMP_RE.search(comment_body)
    if match:
        label = match.group("label").strip().upper()
        if label in VALID_BUMP_LABELS:
            return label

    match = RECOMMENDATION_LINE_RE.search(comment_body)
    if not match:
        return None
    label = re.sub(r"[\s\-]+", "_", match.group("label").strip().upper()).strip("_")
    if label == "NOBUMP":
        label = "NO_BUMP"
    if label in VALID_BUMP_LABELS:
        return label
    return None


def normalize_semver_token(token: str) -> str | None:
    normalized = token.strip()
    if not re.match(r"^v?\d+\.\d+\.\d+$", normalized):
        return None
    normalized = normalized.removeprefix("v")
    major, minor, patch = normalized.split(".")
    return f"{int(major)}.{int(minor)}.{int(patch)}"


def extract_recommended_current_version(comment_body: str) -> str | None:
    arrow_match = NEXT_VERSION_ARROW_RE.search(comment_body)
    if arrow_match:
        return normalize_semver_token(arrow_match.group("current"))

    current_only_match = NEXT_VERSION_CURRENT_ONLY_RE.search(comment_body)
    if current_only_match:
        return normalize_semver_token(current_only_match.group("current"))
    return None
