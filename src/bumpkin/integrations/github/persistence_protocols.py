from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from bumpkin.integrations.github.guards import ApprovalRecord, PublishGuardDecision
from bumpkin.integrations.github.ingress import AppEventEnvelope
from bumpkin.integrations.github.persistence_models import (
    AuditLogRecord,
    PublishDecisionRecord,
    RecommendationSnapshot,
    ReleaseBacklogItem,
    StoredEventRecord,
)
from bumpkin.integrations.github.types import AppEvent

DEFAULT_EVENT_STATUS = "accepted"


class EventPersistenceStore(Protocol):
    def record_event(
        self,
        *,
        envelope: AppEventEnvelope,
        event: AppEvent,
        status: str = DEFAULT_EVENT_STATUS,
    ) -> bool: ...

    def get_event(self, *, provider: str, provider_event_id: str) -> StoredEventRecord | None: ...

    def update_event_status(
        self,
        *,
        provider: str,
        provider_event_id: str,
        status: str,
    ) -> bool: ...

    def list_deferred_merge_events(
        self,
        *,
        provider: str,
        repository: str,
        limit: int = 20,
    ) -> list[StoredEventRecord]: ...


class RecommendationPersistenceStore(Protocol):
    def latest_recommended_label_for_pr(
        self,
        *,
        repository: str,
        pull_request_number: int,
    ) -> str | None: ...

    def latest_recommendation_for_pr(
        self,
        *,
        repository: str,
        pull_request_number: int,
    ) -> RecommendationSnapshot | None: ...

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
    ) -> None: ...


class ReleaseBacklogPersistenceStore(Protocol):
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
    ) -> int: ...

    def list_unreleased_release_backlog_items(
        self,
        *,
        repository: str,
        limit: int = 500,
    ) -> list[ReleaseBacklogItem]: ...

    def mark_release_backlog_items_included(
        self,
        *,
        repository: str,
        backlog_ids: tuple[int, ...],
        release_tag: str,
        included_at: datetime | None = None,
    ) -> int: ...


class ApprovalPersistenceStore(Protocol):
    def record_approval(
        self,
        *,
        approval: ApprovalRecord,
        commit_sha: str,
        source_event_id: str | None = None,
    ) -> int: ...

    def latest_approval_for_pr(
        self,
        *,
        repository: str,
        pull_request_number: int,
    ) -> ApprovalRecord | None: ...

    def delete_approvals(self, *, repository: str, pull_request_number: int) -> int: ...


class PublishDecisionPersistenceStore(Protocol):
    def record_publish_decision(
        self,
        *,
        repository: str,
        pull_request_number: int,
        commit_sha: str,
        decision: PublishGuardDecision,
        policy_snapshot: dict[str, Any],
        evaluated_at: datetime | None = None,
    ) -> int: ...

    def latest_publish_decision_for_pr(
        self,
        *,
        repository: str,
        pull_request_number: int,
    ) -> PublishDecisionRecord | None: ...


class AuditLogStore(Protocol):
    def list_audit_entries(self, *, entity_type: str, entity_id: str) -> list[AuditLogRecord]: ...


class AppStateStore(
    EventPersistenceStore,
    RecommendationPersistenceStore,
    ReleaseBacklogPersistenceStore,
    ApprovalPersistenceStore,
    PublishDecisionPersistenceStore,
    AuditLogStore,
    Protocol,
):
    def close(self) -> None: ...
