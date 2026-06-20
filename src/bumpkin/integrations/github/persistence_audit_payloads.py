from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bumpkin.integrations.github.guards import ApprovalRecord, PublishGuardDecision
from bumpkin.integrations.github.persistence_write_normalization import (
    NormalizedRecommendationSnapshotInput,
    NormalizedReleaseBacklogInclusionInput,
    NormalizedReleaseBacklogWriteInput,
)
from bumpkin.integrations.github.types import AppEvent


@dataclass(frozen=True, slots=True)
class AuditWritePayload:
    entity_type: str
    entity_id: str
    action: str
    actor: str
    details: dict[str, Any]

    def as_kwargs(self) -> dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "action": self.action,
            "actor": self.actor,
            "details": self.details,
        }


def build_event_recorded_payload(
    *,
    provider: str,
    provider_event_id: str,
    event: AppEvent,
    status: str,
) -> AuditWritePayload:
    return AuditWritePayload(
        entity_type="app_event",
        entity_id=f"{provider}:{provider_event_id}",
        action="recorded",
        actor=event.sender_login or "system",
        details={
            "event_type": event.event,
            "repository": event.repository,
            "pull_request_number": event.pull_request_number,
            "status": status,
        },
    )


def build_event_status_updated_payload(
    *,
    provider: str,
    provider_event_id: str,
    status: str,
) -> AuditWritePayload:
    return AuditWritePayload(
        entity_type="app_event",
        entity_id=f"{provider}:{provider_event_id}",
        action="status_updated",
        actor="system",
        details={"status": status},
    )


def build_recommendation_recorded_payload(
    normalized: NormalizedRecommendationSnapshotInput,
) -> AuditWritePayload:
    return AuditWritePayload(
        entity_type="recommendation",
        entity_id=f"{normalized.repository}:{normalized.pull_request_number}",
        action="recorded",
        actor="system",
        details={
            "label": normalized.label,
            "current_version": normalized.current_version,
            "source": normalized.source,
            "source_event_id": normalized.source_event_id,
        },
    )


def build_release_backlog_upserted_payload(
    *,
    normalized: NormalizedReleaseBacklogWriteInput,
    backlog_id: int,
) -> AuditWritePayload:
    return AuditWritePayload(
        entity_type="release_backlog",
        entity_id=f"{normalized.repository}:{normalized.pull_request_number}",
        action="upserted",
        actor="system",
        details={
            "id": backlog_id,
            "merge_commit_sha": normalized.merge_commit_sha,
            "recommended_label": normalized.recommended_label,
            "recommended_current_version": normalized.recommended_current_version,
            "pull_request_title": normalized.pull_request_title,
            "pull_request_author_login": normalized.pull_request_author_login,
            "pull_request_url": normalized.pull_request_url,
            "release_summary": normalized.release_summary,
            "source_event_id": normalized.source_event_id,
        },
    )


def build_release_backlog_included_payload(
    *,
    normalized: NormalizedReleaseBacklogInclusionInput,
    updated_count: int,
) -> AuditWritePayload:
    return AuditWritePayload(
        entity_type="release_backlog",
        entity_id=f"{normalized.repository}:{normalized.release_tag}",
        action="included",
        actor="system",
        details={
            "release_tag": normalized.release_tag,
            "backlog_ids": list(normalized.backlog_ids),
            "updated_count": updated_count,
        },
    )


def build_approval_recorded_payload(
    *,
    approval_id: int,
    approval: ApprovalRecord,
    commit_sha: str,
    source_event_id: str | None,
) -> AuditWritePayload:
    return AuditWritePayload(
        entity_type="approval",
        entity_id=str(approval_id),
        action="recorded",
        actor=approval.approved_by,
        details={
            "repository": approval.repository,
            "pull_request_number": approval.pull_request_number,
            "commit_sha": commit_sha,
            "recommendation_hash": approval.recommendation_hash,
            "source_event_id": source_event_id,
        },
    )


def build_approval_deleted_payload(
    *,
    repository: str,
    pull_request_number: int,
    removed_rows: int,
) -> AuditWritePayload:
    return AuditWritePayload(
        entity_type="approval",
        entity_id=f"{repository}:{pull_request_number}",
        action="deleted",
        actor="system",
        details={"removed_rows": removed_rows},
    )


def build_publish_decision_recorded_payload(
    *,
    decision_id: int,
    repository: str,
    pull_request_number: int,
    commit_sha: str,
    decision: PublishGuardDecision,
) -> AuditWritePayload:
    return AuditWritePayload(
        entity_type="publish_decision",
        entity_id=str(decision_id),
        action="recorded",
        actor="system",
        details={
            "repository": repository,
            "pull_request_number": pull_request_number,
            "commit_sha": commit_sha,
            "allowed": decision.allowed,
            "guard_reasons": list(decision.guard_reasons),
        },
    )
