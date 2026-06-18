from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class StoredEventRecord:
    provider: str
    provider_event_id: str
    event_type: str
    action: str | None
    repository: str | None
    pull_request_number: int | None
    sender_login: str | None
    received_at: datetime
    payload: dict[str, Any]
    payload_hash: str
    headers_hash: str
    status: str


@dataclass(frozen=True, slots=True)
class PublishDecisionRecord:
    repository: str
    pull_request_number: int
    commit_sha: str
    allowed: bool
    reason: str
    guard_reasons: tuple[str, ...]
    evaluated_at: datetime
    policy_snapshot: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AuditLogRecord:
    entity_type: str
    entity_id: str
    action: str
    actor: str
    timestamp: datetime
    details: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RecommendationSnapshot:
    label: str
    current_version: str | None


@dataclass(frozen=True, slots=True)
class ReleaseBacklogItem:
    id: int
    repository: str
    pull_request_number: int
    merge_commit_sha: str
    recommended_label: str
    recommended_current_version: str | None
    merged_at: datetime
    included_in_release_tag: str | None
    included_at: datetime | None
    source_event_id: str | None = None
    pull_request_title: str | None = None
    pull_request_author_login: str | None = None
    pull_request_url: str | None = None
    release_summary: str | None = None
