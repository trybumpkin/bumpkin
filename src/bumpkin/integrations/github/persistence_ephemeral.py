from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bumpkin.integrations.github.guards import ApprovalRecord, PublishGuardDecision
from bumpkin.integrations.github.ingress import AppEventEnvelope
from bumpkin.integrations.github.persistence_models import (
    AuditLogRecord,
    PublishDecisionRecord,
    RecommendationSnapshot,
    ReleaseBacklogItem,
    StoredEventRecord,
)
from bumpkin.integrations.github.persistence_protocols import DEFAULT_EVENT_STATUS
from bumpkin.integrations.github.persistence_recommendation_parsing import (
    normalize_semver_token as _normalize_semver_token,
)
from bumpkin.integrations.github.persistence_serialization import (
    clean_optional_text as _clean_optional_text,
)
from bumpkin.integrations.github.persistence_serialization import (
    normalize_timestamp as _normalize_timestamp,
)
from bumpkin.integrations.github.types import AppEvent


class EphemeralAppStateStore:
    """In-memory store for local runs; unsupported durable records are no-ops."""

    def __init__(self) -> None:
        self._events: dict[tuple[str, str], StoredEventRecord] = {}
        self._recommendations: dict[tuple[str, int], RecommendationSnapshot] = {}
        self._backlog: dict[tuple[str, int], ReleaseBacklogItem] = {}
        self._next_backlog_id = 1

    def close(self) -> None:
        return None

    def record_event(
        self,
        *,
        envelope: AppEventEnvelope,
        event: AppEvent,
        status: str = DEFAULT_EVENT_STATUS,
    ) -> bool:
        provider_key = ("github", envelope.event_id.strip())
        if provider_key in self._events:
            return False
        self._events[provider_key] = StoredEventRecord(
            provider="github",
            provider_event_id=envelope.event_id,
            event_type=event.event,
            action=event.action,
            repository=event.repository,
            pull_request_number=event.pull_request_number,
            sender_login=event.sender_login,
            received_at=envelope.received_at,
            payload=dict(envelope.payload),
            payload_hash=envelope.payload_hash,
            headers_hash=envelope.headers_hash,
            status=status,
        )
        return True

    def get_event(self, *, provider: str, provider_event_id: str) -> StoredEventRecord | None:
        return self._events.get((provider.strip().lower(), provider_event_id.strip()))

    def update_event_status(
        self,
        *,
        provider: str,
        provider_event_id: str,
        status: str,
    ) -> bool:
        key = (provider.strip().lower(), provider_event_id.strip())
        record = self._events.get(key)
        if record is None:
            return False
        self._events[key] = StoredEventRecord(
            provider=record.provider,
            provider_event_id=record.provider_event_id,
            event_type=record.event_type,
            action=record.action,
            repository=record.repository,
            pull_request_number=record.pull_request_number,
            sender_login=record.sender_login,
            received_at=record.received_at,
            payload=record.payload,
            payload_hash=record.payload_hash,
            headers_hash=record.headers_hash,
            status=status,
        )
        return True

    def list_deferred_merge_events(
        self,
        *,
        provider: str,
        repository: str,
        limit: int = 20,
    ) -> list[StoredEventRecord]:
        normalized_provider = provider.strip().lower()
        normalized_repository = repository.strip().lower()
        matches = [
            event
            for (stored_provider, _), event in self._events.items()
            if stored_provider == normalized_provider
            and (event.repository or "").strip().lower() == normalized_repository
            and event.status.startswith("deferred_deploy:")
        ]
        matches.sort(key=lambda event: event.received_at, reverse=True)
        return matches[: max(1, int(limit))]

    def latest_recommended_label_for_pr(
        self,
        *,
        repository: str,
        pull_request_number: int,
    ) -> str | None:
        snapshot = self.latest_recommendation_for_pr(
            repository=repository,
            pull_request_number=pull_request_number,
        )
        return snapshot.label if snapshot is not None else None

    def latest_recommendation_for_pr(
        self,
        *,
        repository: str,
        pull_request_number: int,
    ) -> RecommendationSnapshot | None:
        key = (repository.strip(), int(pull_request_number))
        return self._recommendations.get(key)

    def record_recommendation_snapshot(
        self,
        *,
        repository: str,
        pull_request_number: int,
        label: str,
        current_version: str | None,
        source: str,
        source_event_id: str | None = None,
        recorded_at: datetime | None = None,
    ) -> None:
        _ = source, source_event_id, recorded_at
        key = (repository.strip(), int(pull_request_number))
        self._recommendations[key] = RecommendationSnapshot(
            label=label.strip(),
            current_version=_normalize_semver_token(current_version or "")
            if current_version is not None
            else None,
        )

    def upsert_release_backlog_item(
        self,
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
    ) -> int:
        key = (repository.strip(), int(pull_request_number))
        existing = self._backlog.get(key)
        backlog_id = existing.id if existing is not None else self._next_backlog_id
        if existing is None:
            self._next_backlog_id += 1
        self._backlog[key] = ReleaseBacklogItem(
            id=backlog_id,
            repository=repository.strip(),
            pull_request_number=int(pull_request_number),
            merge_commit_sha=merge_commit_sha.strip(),
            recommended_label=recommended_label.strip(),
            recommended_current_version=_normalize_semver_token(recommended_current_version or "")
            if recommended_current_version is not None
            else None,
            merged_at=_normalize_timestamp(merged_at or datetime.now(UTC)),
            included_in_release_tag=None,
            included_at=None,
            source_event_id=source_event_id,
            pull_request_title=_clean_optional_text(pull_request_title),
            pull_request_author_login=_clean_optional_text(pull_request_author_login),
            pull_request_url=_clean_optional_text(pull_request_url),
            release_summary=_clean_optional_text(release_summary),
        )
        return backlog_id

    def list_unreleased_release_backlog_items(
        self,
        *,
        repository: str,
        limit: int = 500,
    ) -> list[ReleaseBacklogItem]:
        normalized_repository = repository.strip()
        items = [
            item
            for item in self._backlog.values()
            if item.repository == normalized_repository and item.included_in_release_tag is None
        ]
        items.sort(key=lambda item: (item.merged_at, item.id))
        return items[: max(1, int(limit))]

    def mark_release_backlog_items_included(
        self,
        *,
        repository: str,
        backlog_ids: tuple[int, ...],
        release_tag: str,
        included_at: datetime | None = None,
    ) -> int:
        normalized_repository = repository.strip()
        normalized_release_tag = release_tag.strip()
        normalized_included_at = _normalize_timestamp(included_at or datetime.now(UTC))
        target_ids = {int(value) for value in backlog_ids if int(value) > 0}
        updated = 0
        for key, item in list(self._backlog.items()):
            if item.repository != normalized_repository:
                continue
            if item.id not in target_ids or item.included_in_release_tag is not None:
                continue
            self._backlog[key] = ReleaseBacklogItem(
                id=item.id,
                repository=item.repository,
                pull_request_number=item.pull_request_number,
                merge_commit_sha=item.merge_commit_sha,
                recommended_label=item.recommended_label,
                recommended_current_version=item.recommended_current_version,
                merged_at=item.merged_at,
                included_in_release_tag=normalized_release_tag,
                included_at=normalized_included_at,
                source_event_id=item.source_event_id,
                pull_request_title=item.pull_request_title,
                pull_request_author_login=item.pull_request_author_login,
                pull_request_url=item.pull_request_url,
                release_summary=item.release_summary,
            )
            updated += 1
        return updated

    def record_approval(
        self,
        *,
        approval: ApprovalRecord,
        commit_sha: str,
        source_event_id: str | None = None,
    ) -> int:
        _ = approval, commit_sha, source_event_id
        return 0

    def latest_approval_for_pr(
        self,
        *,
        repository: str,
        pull_request_number: int,
    ) -> ApprovalRecord | None:
        _ = repository, pull_request_number
        return None

    def delete_approvals(self, *, repository: str, pull_request_number: int) -> int:
        _ = repository, pull_request_number
        return 0

    def record_publish_decision(
        self,
        *,
        repository: str,
        pull_request_number: int,
        commit_sha: str,
        decision: PublishGuardDecision,
        policy_snapshot: dict[str, Any],
        evaluated_at: datetime | None = None,
    ) -> int:
        _ = (
            repository,
            pull_request_number,
            commit_sha,
            decision,
            policy_snapshot,
            evaluated_at,
        )
        return 0

    def latest_publish_decision_for_pr(
        self,
        *,
        repository: str,
        pull_request_number: int,
    ) -> PublishDecisionRecord | None:
        _ = repository, pull_request_number
        return None

    def list_audit_entries(self, *, entity_type: str, entity_id: str) -> list[AuditLogRecord]:
        _ = entity_type, entity_id
        return []
