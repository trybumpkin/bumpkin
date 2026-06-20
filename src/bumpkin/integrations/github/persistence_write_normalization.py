from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from bumpkin.integrations.github.persistence_recommendation_parsing import (
    extract_recommended_label as _extract_recommended_label,
)
from bumpkin.integrations.github.persistence_recommendation_parsing import (
    normalize_semver_token as _normalize_semver_token,
)
from bumpkin.integrations.github.persistence_serialization import (
    clean_optional_text as _clean_optional_text,
)
from bumpkin.integrations.github.persistence_serialization import (
    to_iso as _to_iso,
)


@dataclass(frozen=True, slots=True)
class NormalizedRecommendationSnapshotInput:
    repository: str
    pull_request_number: int
    label: str
    current_version: str | None
    source: str
    source_event_id: str | None
    recorded_at: str


@dataclass(frozen=True, slots=True)
class NormalizedReleaseBacklogWriteInput:
    repository: str
    pull_request_number: int
    merge_commit_sha: str
    recommended_label: str
    recommended_current_version: str | None
    pull_request_title: str | None
    pull_request_author_login: str | None
    pull_request_url: str | None
    release_summary: str | None
    source_event_id: str | None
    merged_at: str


@dataclass(frozen=True, slots=True)
class NormalizedReleaseBacklogInclusionInput:
    repository: str
    release_tag: str
    backlog_ids: tuple[int, ...]
    included_at: str


def normalize_recommendation_snapshot_input(
    *,
    repository: str,
    pull_request_number: int,
    label: str,
    current_version: str | None,
    source: str,
    source_event_id: str | None = None,
    recorded_at: datetime | None = None,
) -> NormalizedRecommendationSnapshotInput:
    normalized_repository = repository.strip()
    if not normalized_repository:
        raise ValueError("repository is required to record recommendation snapshot.")
    normalized_label = _extract_recommended_label(f"Proposed bump (court): {label}")
    if normalized_label is None:
        raise ValueError("label must be one of MAJOR, MINOR, PATCH, NO_BUMP.")
    return NormalizedRecommendationSnapshotInput(
        repository=normalized_repository,
        pull_request_number=pull_request_number,
        label=normalized_label,
        current_version=(
            _normalize_semver_token(current_version) if current_version is not None else None
        ),
        source=source.strip() or "unknown",
        source_event_id=source_event_id.strip() if source_event_id is not None else None,
        recorded_at=_to_iso(recorded_at or datetime.now(timezone.utc)),  # noqa: UP017
    )


def normalize_release_backlog_write_input(
    *,
    repository: str,
    pull_request_number: int,
    merge_commit_sha: str,
    recommended_label: str,
    recommended_current_version: str | None,
    pull_request_title: str | None = None,
    pull_request_author_login: str | None = None,
    pull_request_url: str | None = None,
    release_summary: str | None = None,
    source_event_id: str | None = None,
    merged_at: datetime | None = None,
) -> NormalizedReleaseBacklogWriteInput:
    normalized_repository = repository.strip()
    if not normalized_repository:
        raise ValueError("repository is required to upsert release backlog item.")
    normalized_merge_commit_sha = merge_commit_sha.strip()
    if not normalized_merge_commit_sha:
        raise ValueError("merge_commit_sha is required to upsert release backlog item.")
    normalized_label = _extract_recommended_label(f"Proposed bump (court): {recommended_label}")
    if normalized_label is None:
        raise ValueError("recommended_label must be one of MAJOR, MINOR, PATCH, NO_BUMP.")
    return NormalizedReleaseBacklogWriteInput(
        repository=normalized_repository,
        pull_request_number=pull_request_number,
        merge_commit_sha=normalized_merge_commit_sha,
        recommended_label=normalized_label,
        recommended_current_version=(
            _normalize_semver_token(recommended_current_version)
            if recommended_current_version is not None
            else None
        ),
        pull_request_title=_clean_optional_text(pull_request_title),
        pull_request_author_login=_clean_optional_text(pull_request_author_login),
        pull_request_url=_clean_optional_text(pull_request_url),
        release_summary=_clean_optional_text(release_summary),
        source_event_id=source_event_id.strip() if source_event_id is not None else None,
        merged_at=_to_iso(merged_at or datetime.now(timezone.utc)),  # noqa: UP017
    )


def normalize_release_backlog_inclusion_input(
    *,
    repository: str,
    backlog_ids: tuple[int, ...],
    release_tag: str,
    included_at: datetime | None = None,
) -> NormalizedReleaseBacklogInclusionInput | None:
    normalized_repository = repository.strip()
    if not normalized_repository:
        return None
    normalized_release_tag = release_tag.strip()
    if not normalized_release_tag:
        raise ValueError("release_tag is required to mark release backlog items.")
    if not backlog_ids:
        return None
    normalized_ids = tuple(sorted({int(value) for value in backlog_ids if int(value) > 0}))
    if not normalized_ids:
        return None
    return NormalizedReleaseBacklogInclusionInput(
        repository=normalized_repository,
        release_tag=normalized_release_tag,
        backlog_ids=normalized_ids,
        included_at=_to_iso(included_at or datetime.now(timezone.utc)),  # noqa: UP017
    )
