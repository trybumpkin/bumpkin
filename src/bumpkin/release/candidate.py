from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import cast

from bumpkin.release.models import (
    ReleaseCandidate,
    ReleasePlan,
    ReleaseScopedPullRequest,
)

_RELEASE_CANDIDATE_FORMAT_VERSION = 1


def _coerce_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise RuntimeError(f"Release candidate field '{field_name}' must be an integer.")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if normalized:
            try:
                return int(normalized)
            except ValueError as exc:
                raise RuntimeError(
                    f"Release candidate field '{field_name}' must be an integer."
                ) from exc
    raise RuntimeError(f"Release candidate field '{field_name}' must be an integer.")


def _coerce_string(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _coerce_optional_string(value: object) -> str | None:
    normalized = _coerce_string(value)
    return normalized or None


def _parse_iso8601(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)  # noqa: UP017
    return parsed.astimezone(timezone.utc)  # noqa: UP017


def _serialize_pull_request(pull_request: ReleaseScopedPullRequest) -> dict[str, object]:
    return {
        "repository": pull_request.repository,
        "number": pull_request.number,
        "title": pull_request.title,
        "url": pull_request.url,
        "author_login": pull_request.author_login,
        "merged_at": pull_request.merged_at.isoformat(),
        "merge_commit_sha": pull_request.merge_commit_sha,
        "base_ref": pull_request.base_ref,
        "base_sha": pull_request.base_sha,
        "head_ref": pull_request.head_ref,
        "head_sha": pull_request.head_sha,
        "labels": list(pull_request.labels),
    }


def _deserialize_pull_request(payload: object) -> ReleaseScopedPullRequest:
    if not isinstance(payload, dict):
        raise RuntimeError("Release candidate payload contains an invalid pull request entry.")
    payload_map = cast("dict[str, object]", payload)
    return ReleaseScopedPullRequest(
        repository=_coerce_string(payload_map.get("repository", "")),
        number=_coerce_int(payload_map.get("number", 0), field_name="number"),
        title=_coerce_string(payload_map.get("title", "")),
        url=_coerce_string(payload_map.get("url", "")),
        author_login=_coerce_optional_string(payload_map.get("author_login", "")),
        merged_at=_parse_iso8601(_coerce_string(payload_map.get("merged_at", ""))),
        merge_commit_sha=_coerce_string(payload_map.get("merge_commit_sha", "")),
        base_ref=_coerce_optional_string(payload_map.get("base_ref", "")),
        base_sha=_coerce_optional_string(payload_map.get("base_sha", "")),
        head_ref=_coerce_optional_string(payload_map.get("head_ref", "")),
        head_sha=_coerce_optional_string(payload_map.get("head_sha", "")),
        labels=tuple(
            str(item).strip()
            for item in cast("list[object]", payload_map.get("labels", []))
            if str(item).strip()
        ),
    )


def _candidate_fingerprint_payload(
    *,
    repository: str,
    target_ref: str,
    target_sha: str,
    base_tag_input: str,
    previous_tag: str | None,
    next_tag: str | None,
    release_label: str | None,
    status: str,
    pull_requests: tuple[ReleaseScopedPullRequest, ...] | list[ReleaseScopedPullRequest],
    preview_notes: str,
    published_release_body: str,
) -> dict[str, object]:
    return {
        "repository": repository,
        "target_ref": target_ref,
        "target_sha": target_sha,
        "base_tag_input": base_tag_input,
        "previous_tag": previous_tag,
        "next_tag": next_tag,
        "release_label": release_label,
        "status": status,
        "preview_notes": preview_notes,
        "published_release_body": published_release_body,
        "pull_requests": [
            {
                "number": pull_request.number,
                "merge_commit_sha": pull_request.merge_commit_sha,
            }
            for pull_request in pull_requests
        ],
    }


def _candidate_fingerprint(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _build_release_candidate(
    *,
    plan: ReleasePlan,
    base_tag_input: str,
    source_operation: str,
    source_run_id: str | None,
) -> ReleaseCandidate:
    fingerprint = _candidate_fingerprint(
        _candidate_fingerprint_payload(
            repository=plan.repository,
            target_ref=plan.target_ref,
            target_sha=plan.target_sha,
            base_tag_input=base_tag_input,
            previous_tag=plan.previous_tag,
            next_tag=plan.next_tag,
            release_label=plan.release_label,
            status=plan.status,
            pull_requests=plan.pull_requests,
            preview_notes=plan.preview_notes,
            published_release_body=plan.published_release_body,
        )
    )
    return ReleaseCandidate(
        format_version=_RELEASE_CANDIDATE_FORMAT_VERSION,
        source_operation=source_operation,
        source_run_id=source_run_id,
        repository=plan.repository,
        target_ref=plan.target_ref,
        target_sha=plan.target_sha,
        base_tag_input=base_tag_input,
        previous_tag=plan.previous_tag,
        next_tag=plan.next_tag,
        release_label=plan.release_label,
        status=plan.status,
        preview_notes=plan.preview_notes,
        published_release_body=plan.published_release_body,
        notes=tuple(plan.notes),
        pull_requests=tuple(plan.pull_requests),
        fingerprint=fingerprint,
    )


def _serialize_release_candidate(candidate: ReleaseCandidate) -> dict[str, object]:
    return {
        "format_version": candidate.format_version,
        "source_operation": candidate.source_operation,
        "source_run_id": candidate.source_run_id,
        "repository": candidate.repository,
        "target_ref": candidate.target_ref,
        "target_sha": candidate.target_sha,
        "base_tag_input": candidate.base_tag_input,
        "previous_tag": candidate.previous_tag,
        "next_tag": candidate.next_tag,
        "release_label": candidate.release_label,
        "status": candidate.status,
        "preview_notes": candidate.preview_notes,
        "published_release_body": candidate.published_release_body,
        "notes": list(candidate.notes),
        "pull_requests": [
            _serialize_pull_request(pull_request) for pull_request in candidate.pull_requests
        ],
        "fingerprint": candidate.fingerprint,
    }


def _deserialize_release_candidate(payload: object) -> ReleaseCandidate:
    if not isinstance(payload, dict):
        raise RuntimeError("Release candidate artifact did not contain a JSON object.")
    payload_map = cast("dict[str, object]", payload)
    pull_requests_raw = payload_map.get("pull_requests", [])
    if not isinstance(pull_requests_raw, list):
        raise RuntimeError("Release candidate artifact is missing pull request data.")
    notes_raw = payload_map.get("notes", [])
    if not isinstance(notes_raw, list):
        raise RuntimeError("Release candidate artifact is missing notes data.")
    candidate = ReleaseCandidate(
        format_version=_coerce_int(
            payload_map.get("format_version", 0), field_name="format_version"
        ),
        source_operation=_coerce_string(payload_map.get("source_operation", "")),
        source_run_id=_coerce_optional_string(payload_map.get("source_run_id", "")),
        repository=_coerce_string(payload_map.get("repository", "")),
        target_ref=_coerce_string(payload_map.get("target_ref", "")),
        target_sha=_coerce_string(payload_map.get("target_sha", "")),
        base_tag_input=_coerce_string(payload_map.get("base_tag_input", "")),
        previous_tag=_coerce_optional_string(payload_map.get("previous_tag", "")),
        next_tag=_coerce_optional_string(payload_map.get("next_tag", "")),
        release_label=_coerce_optional_string(payload_map.get("release_label", "")),
        status=_coerce_string(payload_map.get("status", "")),
        preview_notes=str(payload_map.get("preview_notes", "")),
        published_release_body=str(payload_map.get("published_release_body", "")),
        notes=tuple(str(note).strip() for note in notes_raw if str(note).strip()),
        pull_requests=tuple(_deserialize_pull_request(item) for item in pull_requests_raw),
        fingerprint=_coerce_string(payload_map.get("fingerprint", "")),
    )
    if candidate.format_version != _RELEASE_CANDIDATE_FORMAT_VERSION:
        raise RuntimeError(
            f"Unsupported release candidate format version: {candidate.format_version}."
        )
    expected_fingerprint = _candidate_fingerprint(
        _candidate_fingerprint_payload(
            repository=candidate.repository,
            target_ref=candidate.target_ref,
            target_sha=candidate.target_sha,
            base_tag_input=candidate.base_tag_input,
            previous_tag=candidate.previous_tag,
            next_tag=candidate.next_tag,
            release_label=candidate.release_label,
            status=candidate.status,
            pull_requests=candidate.pull_requests,
            preview_notes=candidate.preview_notes,
            published_release_body=candidate.published_release_body,
        )
    )
    if candidate.fingerprint != expected_fingerprint:
        raise RuntimeError("Release candidate fingerprint is invalid.")
    return candidate


def _release_candidate_to_plan(candidate: ReleaseCandidate) -> ReleasePlan:
    return ReleasePlan(
        repository=candidate.repository,
        target_ref=candidate.target_ref,
        target_sha=candidate.target_sha,
        previous_tag=candidate.previous_tag,
        next_tag=candidate.next_tag,
        release_label=candidate.release_label,
        pull_requests=candidate.pull_requests,
        recommendations=(),
        preview_notes=candidate.preview_notes,
        published_release_body=candidate.published_release_body,
        notes=candidate.notes,
        status=candidate.status,
    )


__all__ = [
    "_build_release_candidate",
    "_candidate_fingerprint",
    "_candidate_fingerprint_payload",
    "_coerce_int",
    "_deserialize_pull_request",
    "_deserialize_release_candidate",
    "_parse_iso8601",
    "_release_candidate_to_plan",
    "_serialize_pull_request",
    "_serialize_release_candidate",
]
