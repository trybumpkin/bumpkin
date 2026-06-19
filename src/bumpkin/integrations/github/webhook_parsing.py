from __future__ import annotations

import re
from collections.abc import Mapping

from bumpkin.integrations.github.ingress import (
    OUTCOME_ACCEPTED,
    OUTCOME_DUPLICATE_IGNORED,
    OUTCOME_REJECTED_SIGNATURE,
    OUTCOME_UNSUPPORTED_EVENT,
    OUTCOME_UNSUPPORTED_PROVIDER,
)

_VERSION_TOKEN_RE = re.compile(r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")
_VALID_BUMP_LABELS = frozenset({"MAJOR", "MINOR", "PATCH", "NO_BUMP"})


def _normalize_headers(headers: Mapping[str, object]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in headers.items():
        normalized[str(key).strip().lower()] = str(value).strip()
    return normalized


def _status_for_outcome(outcome: str) -> int:
    if outcome == OUTCOME_ACCEPTED:
        return 202
    if outcome == OUTCOME_DUPLICATE_IGNORED:
        return 200
    if outcome == OUTCOME_REJECTED_SIGNATURE:
        return 401
    if outcome == OUTCOME_UNSUPPORTED_EVENT:
        return 202
    if outcome == OUTCOME_UNSUPPORTED_PROVIDER:
        return 400
    return 500


def _normalize_bump_label(token: str) -> str | None:
    normalized = token.strip().upper().replace("-", "_")
    if normalized == "NOBUMP":
        normalized = "NO_BUMP"
    if normalized in _VALID_BUMP_LABELS:
        return normalized
    return None


def _normalize_version_token(token: str) -> str | None:
    match = _VERSION_TOKEN_RE.match(token.strip())
    if not match:
        return None
    return f"{int(match.group('major'))}.{int(match.group('minor'))}.{int(match.group('patch'))}"


def _extract_pull_request_metadata(payload: Mapping[str, object]) -> dict[str, str | None]:
    pull_request = payload.get("pull_request")
    if not isinstance(pull_request, Mapping):
        return {
            "pull_request_title": None,
            "pull_request_author_login": None,
            "pull_request_url": None,
            "release_summary": None,
        }
    user = pull_request.get("user")
    author_login = None
    if isinstance(user, Mapping):
        author_login = str(user.get("login", "")).strip() or None
    title = str(pull_request.get("title", "")).strip() or None
    html_url = str(pull_request.get("html_url", "")).strip() or None
    return {
        "pull_request_title": title,
        "pull_request_author_login": author_login,
        "pull_request_url": html_url,
        "release_summary": title,
    }


def _extract_repository_default_branch(payload: Mapping[str, object]) -> str | None:
    repository = payload.get("repository")
    if not isinstance(repository, Mapping):
        return None
    default_branch = str(repository.get("default_branch", "")).strip()
    return default_branch or None


__all__ = [
    "_extract_pull_request_metadata",
    "_extract_repository_default_branch",
    "_normalize_bump_label",
    "_normalize_headers",
    "_normalize_version_token",
    "_status_for_outcome",
]
