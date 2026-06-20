from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Self, cast

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - exercised in deployment, optional in local dev
    psycopg = None
    dict_row = None

from bumpkin.integrations.github.guards import ApprovalRecord, PublishGuardDecision
from bumpkin.integrations.github.ingress import AppEventEnvelope
from bumpkin.integrations.github.persistence_migrations import apply_postgres_migrations
from bumpkin.integrations.github.persistence_models import (
    AuditLogRecord,
    PublishDecisionRecord,
    RecommendationSnapshot,
    ReleaseBacklogItem,
    StoredEventRecord,
)
from bumpkin.integrations.github.persistence_protocols import DEFAULT_EVENT_STATUS
from bumpkin.integrations.github.persistence_recommendation_parsing import (
    extract_recommended_label as _extract_recommended_label,
)
from bumpkin.integrations.github.persistence_recommendation_parsing import (
    normalize_semver_token as _normalize_semver_token,
)
from bumpkin.integrations.github.persistence_record_parsing import (
    build_approval_record as _build_approval_record,
)
from bumpkin.integrations.github.persistence_record_parsing import (
    build_audit_log_record as _build_audit_log_record,
)
from bumpkin.integrations.github.persistence_record_parsing import (
    build_publish_decision_record as _build_publish_decision_record,
)
from bumpkin.integrations.github.persistence_record_parsing import (
    build_recommendation_snapshot_from_row as _build_recommendation_snapshot_from_row,
)
from bumpkin.integrations.github.persistence_record_parsing import (
    build_release_backlog_item as _build_release_backlog_item,
)
from bumpkin.integrations.github.persistence_record_parsing import (
    build_stored_event_record as _build_stored_event_record,
)
from bumpkin.integrations.github.persistence_record_parsing import (
    extract_recommendation_snapshot_from_payload as _extract_recommendation_snapshot_from_payload,
)
from bumpkin.integrations.github.persistence_serialization import (
    clean_optional_text as _clean_optional_text,
)
from bumpkin.integrations.github.persistence_serialization import (
    json_dump as _json_dump,
)
from bumpkin.integrations.github.persistence_serialization import (
    normalize_timestamp as _normalize_timestamp,
)
from bumpkin.integrations.github.persistence_serialization import (
    postgres_row_mapping as _postgres_row_mapping,
)
from bumpkin.integrations.github.persistence_serialization import (
    to_iso as _to_iso,
)
from bumpkin.integrations.github.types import AppEvent


class PostgresAppStateStore:
    def __init__(self, database_url: str) -> None:
        if psycopg is None or dict_row is None:
            raise RuntimeError(
                "Postgres support requires `psycopg` to be installed in the runtime environment."
            )
        row_factory = cast("Any", dict_row)
        self._connection = psycopg.connect(database_url, row_factory=row_factory)
        apply_postgres_migrations(self._connection)

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def record_event(
        self,
        *,
        envelope: AppEventEnvelope,
        event: AppEvent,
        status: str = DEFAULT_EVENT_STATUS,
    ) -> bool:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO app_events (
                        provider,
                        provider_event_id,
                        event_type,
                        action,
                        repository,
                        pull_request_number,
                        sender_login,
                        received_at,
                        payload,
                        payload_hash,
                        headers_hash,
                        status
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        envelope.source,
                        envelope.event_id,
                        event.event,
                        event.action,
                        event.repository,
                        event.pull_request_number,
                        event.sender_login,
                        _to_iso(envelope.received_at),
                        _json_dump(envelope.payload),
                        envelope.payload_hash,
                        envelope.headers_hash,
                        status,
                    ),
                )
        except Exception as err:
            if psycopg is not None and isinstance(err, psycopg.IntegrityError):
                self._connection.rollback()
                return False
            self._connection.rollback()
            raise

        self._record_audit(
            entity_type="app_event",
            entity_id=f"{envelope.source}:{envelope.event_id}",
            action="recorded",
            actor=event.sender_login or "system",
            details={
                "event_type": event.event,
                "repository": event.repository,
                "pull_request_number": event.pull_request_number,
                "status": status,
            },
        )
        self._connection.commit()
        return True

    def get_event(self, *, provider: str, provider_event_id: str) -> StoredEventRecord | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT provider, provider_event_id, event_type, action, repository,
                       pull_request_number, sender_login, received_at, payload,
                       payload_hash, headers_hash, status
                FROM app_events
                WHERE provider = %s AND provider_event_id = %s
                LIMIT 1
                """,
                (provider, provider_event_id),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        row_map = _postgres_row_mapping(row)
        return _build_stored_event_record(row_map)

    def update_event_status(
        self,
        *,
        provider: str,
        provider_event_id: str,
        status: str,
    ) -> bool:
        normalized_status = status.strip()
        if not normalized_status:
            raise ValueError("status must not be empty.")
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE app_events
                SET status = %s
                WHERE provider = %s AND provider_event_id = %s
                """,
                (normalized_status, provider, provider_event_id),
            )
            updated = int(cursor.rowcount)
        if updated <= 0:
            self._connection.rollback()
            return False
        self._record_audit(
            entity_type="app_event",
            entity_id=f"{provider}:{provider_event_id}",
            action="status_updated",
            actor="system",
            details={"status": normalized_status},
        )
        self._connection.commit()
        return True

    def list_deferred_merge_events(
        self,
        *,
        provider: str,
        repository: str,
        limit: int = 20,
    ) -> list[StoredEventRecord]:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT e.provider, e.provider_event_id, e.event_type, e.action, e.repository,
                       e.pull_request_number, e.sender_login, e.received_at, e.payload,
                       e.payload_hash, e.headers_hash, e.status
                FROM app_events AS e
                LEFT JOIN app_recommendations AS r
                  ON r.source_event_id = e.provider_event_id
                WHERE e.provider = %s
                  AND e.repository = %s
                  AND e.event_type = 'pull_request'
                  AND e.action = 'closed'
                  AND e.status LIKE 'deferred_deploy:%%'
                  AND r.source_event_id IS NULL
                ORDER BY e.received_at ASC, e.id ASC
                LIMIT %s
                """,
                (provider, repository, max(1, int(limit))),
            )
            rows = cursor.fetchall()
        return [_build_stored_event_record(_postgres_row_mapping(row)) for row in rows]

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
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT label, current_version
                FROM app_recommendations
                WHERE repository = %s
                  AND pull_request_number = %s
                ORDER BY recorded_at DESC, id DESC
                LIMIT 1
                """,
                (repository, pull_request_number),
            )
            snapshot_row = cursor.fetchone()
        if snapshot_row is not None:
            return _build_recommendation_snapshot_from_row(_postgres_row_mapping(snapshot_row))

        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT payload
                FROM app_events
                WHERE repository = %s
                  AND pull_request_number = %s
                  AND event_type = 'issue_comment'
                ORDER BY received_at DESC, id DESC
                LIMIT 250
                """,
                (repository, pull_request_number),
            )
            rows = cursor.fetchall()
        for row in rows:
            row_map = _postgres_row_mapping(row)
            payload = json.loads(str(row_map["payload"]))
            snapshot = _extract_recommendation_snapshot_from_payload(payload)
            if snapshot is not None:
                return snapshot
        return None

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
        normalized_repository = repository.strip()
        if not normalized_repository:
            raise ValueError("repository is required to record recommendation snapshot.")
        normalized_label = _extract_recommended_label(f"Proposed bump (court): {label}")
        if normalized_label is None:
            raise ValueError("label must be one of MAJOR, MINOR, PATCH, NO_BUMP.")
        normalized_source = source.strip() or "unknown"
        normalized_current_version = (
            _normalize_semver_token(current_version) if current_version is not None else None
        )
        normalized_recorded_at = _to_iso(recorded_at or datetime.now(timezone.utc))  # noqa: UP017
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO app_recommendations (
                    repository,
                    pull_request_number,
                    label,
                    current_version,
                    source,
                    source_event_id,
                    recorded_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(repository, pull_request_number)
                DO UPDATE SET
                    label = EXCLUDED.label,
                    current_version = EXCLUDED.current_version,
                    source = EXCLUDED.source,
                    source_event_id = EXCLUDED.source_event_id,
                    recorded_at = EXCLUDED.recorded_at
                """,
                (
                    normalized_repository,
                    pull_request_number,
                    normalized_label,
                    normalized_current_version,
                    normalized_source,
                    source_event_id.strip() if source_event_id is not None else None,
                    normalized_recorded_at,
                ),
            )
        self._record_audit(
            entity_type="recommendation",
            entity_id=f"{normalized_repository}:{pull_request_number}",
            action="recorded",
            actor="system",
            details={
                "label": normalized_label,
                "current_version": normalized_current_version,
                "source": normalized_source,
                "source_event_id": source_event_id,
            },
        )
        self._connection.commit()

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
        normalized_repository = repository.strip()
        if not normalized_repository:
            raise ValueError("repository is required to upsert release backlog item.")
        normalized_merge_commit_sha = merge_commit_sha.strip()
        if not normalized_merge_commit_sha:
            raise ValueError("merge_commit_sha is required to upsert release backlog item.")
        normalized_label = _extract_recommended_label(f"Proposed bump (court): {recommended_label}")
        if normalized_label is None:
            raise ValueError("recommended_label must be one of MAJOR, MINOR, PATCH, NO_BUMP.")
        normalized_current_version = (
            _normalize_semver_token(recommended_current_version)
            if recommended_current_version is not None
            else None
        )
        normalized_pull_request_title = _clean_optional_text(pull_request_title)
        normalized_pull_request_author_login = _clean_optional_text(pull_request_author_login)
        normalized_pull_request_url = _clean_optional_text(pull_request_url)
        normalized_release_summary = _clean_optional_text(release_summary)
        normalized_merged_at = _to_iso(merged_at or datetime.now(timezone.utc))  # noqa: UP017
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO app_release_backlog (
                    repository,
                    pull_request_number,
                    merge_commit_sha,
                    recommended_label,
                    recommended_current_version,
                    pull_request_title,
                    pull_request_author_login,
                    pull_request_url,
                    release_summary,
                    source_event_id,
                    merged_at,
                    included_in_release_tag,
                    included_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL)
                ON CONFLICT(repository, pull_request_number)
                DO UPDATE SET
                    merge_commit_sha = EXCLUDED.merge_commit_sha,
                    recommended_label = EXCLUDED.recommended_label,
                    recommended_current_version = EXCLUDED.recommended_current_version,
                    pull_request_title = EXCLUDED.pull_request_title,
                    pull_request_author_login = EXCLUDED.pull_request_author_login,
                    pull_request_url = EXCLUDED.pull_request_url,
                    release_summary = EXCLUDED.release_summary,
                    source_event_id = EXCLUDED.source_event_id,
                    merged_at = EXCLUDED.merged_at,
                    updated_at = NOW()
                RETURNING id
                """,
                (
                    normalized_repository,
                    pull_request_number,
                    normalized_merge_commit_sha,
                    normalized_label,
                    normalized_current_version,
                    normalized_pull_request_title,
                    normalized_pull_request_author_login,
                    normalized_pull_request_url,
                    normalized_release_summary,
                    source_event_id.strip() if source_event_id is not None else None,
                    normalized_merged_at,
                ),
            )
            row = cursor.fetchone()
        if row is None:
            raise RuntimeError("Postgres did not return id for release backlog upsert.")
        row_map = _postgres_row_mapping(row)
        if row_map["id"] is None:
            raise RuntimeError("Postgres did not return id for release backlog upsert.")
        backlog_id = int(row_map["id"])
        self._record_audit(
            entity_type="release_backlog",
            entity_id=f"{normalized_repository}:{pull_request_number}",
            action="upserted",
            actor="system",
            details={
                "id": backlog_id,
                "merge_commit_sha": normalized_merge_commit_sha,
                "recommended_label": normalized_label,
                "recommended_current_version": normalized_current_version,
                "pull_request_title": normalized_pull_request_title,
                "pull_request_author_login": normalized_pull_request_author_login,
                "pull_request_url": normalized_pull_request_url,
                "release_summary": normalized_release_summary,
                "source_event_id": source_event_id,
            },
        )
        self._connection.commit()
        return backlog_id

    def list_unreleased_release_backlog_items(
        self,
        *,
        repository: str,
        limit: int = 500,
    ) -> list[ReleaseBacklogItem]:
        normalized_repository = repository.strip()
        if not normalized_repository:
            return []
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, repository, pull_request_number, merge_commit_sha,
                       recommended_label, recommended_current_version,
                       pull_request_title, pull_request_author_login, pull_request_url,
                       release_summary, source_event_id,
                       merged_at, included_in_release_tag, included_at
                FROM app_release_backlog
                WHERE repository = %s
                  AND included_in_release_tag IS NULL
                ORDER BY merged_at ASC, id ASC
                LIMIT %s
                """,
                (normalized_repository, max(1, int(limit))),
            )
            rows = cursor.fetchall()
        return [_build_release_backlog_item(_postgres_row_mapping(row)) for row in rows]

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
        if not normalized_repository:
            return 0
        if not normalized_release_tag:
            raise ValueError("release_tag is required to mark release backlog items.")
        if not backlog_ids:
            return 0
        normalized_ids = tuple(sorted({int(value) for value in backlog_ids if int(value) > 0}))
        if not normalized_ids:
            return 0
        normalized_included_at = _to_iso(included_at or datetime.now(timezone.utc))  # noqa: UP017
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE app_release_backlog
                SET included_in_release_tag = %s,
                    included_at = %s,
                    updated_at = NOW()
                WHERE repository = %s
                  AND id = ANY(%s)
                  AND included_in_release_tag IS NULL
                """,
                (
                    normalized_release_tag,
                    normalized_included_at,
                    normalized_repository,
                    list(normalized_ids),
                ),
            )
            updated_count = int(cursor.rowcount or 0)
        if updated_count > 0:
            self._record_audit(
                entity_type="release_backlog",
                entity_id=f"{normalized_repository}:{normalized_release_tag}",
                action="included",
                actor="system",
                details={
                    "release_tag": normalized_release_tag,
                    "backlog_ids": list(normalized_ids),
                    "updated_count": updated_count,
                },
            )
        self._connection.commit()
        return updated_count

    def record_approval(
        self,
        *,
        approval: ApprovalRecord,
        commit_sha: str,
        source_event_id: str | None = None,
    ) -> int:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO app_approvals (
                    repository,
                    pull_request_number,
                    commit_sha,
                    approved_label,
                    recommendation_hash,
                    approved_by,
                    approved_at,
                    source_event_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    approval.repository,
                    approval.pull_request_number,
                    commit_sha,
                    approval.approved_label,
                    approval.recommendation_hash,
                    approval.approved_by,
                    _to_iso(approval.approved_at),
                    source_event_id,
                ),
            )
            row = cursor.fetchone()
        if row is None:
            raise RuntimeError("Postgres did not return id for insert operation.")
        row_map = _postgres_row_mapping(row)
        if row_map["id"] is None:
            raise RuntimeError("Postgres did not return id for insert operation.")
        approval_id = int(row_map["id"])
        self._record_audit(
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
        self._connection.commit()
        return approval_id

    def latest_approval_for_pr(
        self,
        *,
        repository: str,
        pull_request_number: int,
    ) -> ApprovalRecord | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT repository, pull_request_number, approved_label,
                       recommendation_hash, approved_by, approved_at
                FROM app_approvals
                WHERE repository = %s AND pull_request_number = %s
                ORDER BY approved_at DESC, id DESC
                LIMIT 1
                """,
                (repository, pull_request_number),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return _build_approval_record(_postgres_row_mapping(row))

    def delete_approvals(self, *, repository: str, pull_request_number: int) -> int:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM app_approvals
                WHERE repository = %s AND pull_request_number = %s
                """,
                (repository, pull_request_number),
            )
            removed = int(cursor.rowcount)
        if removed > 0:
            self._record_audit(
                entity_type="approval",
                entity_id=f"{repository}:{pull_request_number}",
                action="deleted",
                actor="system",
                details={"removed_rows": removed},
            )
            self._connection.commit()
        return removed

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
        normalized_evaluated_at = _normalize_timestamp(
            evaluated_at or datetime.now(timezone.utc),  # noqa: UP017
        )
        guard_reasons = list(decision.guard_reasons)
        reason = guard_reasons[0] if guard_reasons else "allowed"
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO publish_decisions (
                    repository,
                    pull_request_number,
                    commit_sha,
                    allowed,
                    reason,
                    guard_reasons,
                    evaluated_at,
                    policy_snapshot
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    repository,
                    pull_request_number,
                    commit_sha,
                    decision.allowed,
                    reason,
                    _json_dump({"guard_reasons": guard_reasons}),
                    _to_iso(normalized_evaluated_at),
                    _json_dump(policy_snapshot),
                ),
            )
            row = cursor.fetchone()
        if row is None:
            raise RuntimeError("Postgres did not return id for insert operation.")
        row_map = _postgres_row_mapping(row)
        if row_map["id"] is None:
            raise RuntimeError("Postgres did not return id for insert operation.")
        decision_id = int(row_map["id"])
        self._record_audit(
            entity_type="publish_decision",
            entity_id=str(decision_id),
            action="recorded",
            actor="system",
            details={
                "repository": repository,
                "pull_request_number": pull_request_number,
                "commit_sha": commit_sha,
                "allowed": decision.allowed,
                "guard_reasons": guard_reasons,
            },
        )
        self._connection.commit()
        return decision_id

    def latest_publish_decision_for_pr(
        self,
        *,
        repository: str,
        pull_request_number: int,
    ) -> PublishDecisionRecord | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT repository, pull_request_number, commit_sha, allowed, reason,
                       guard_reasons, evaluated_at, policy_snapshot
                FROM publish_decisions
                WHERE repository = %s AND pull_request_number = %s
                ORDER BY evaluated_at DESC, id DESC
                LIMIT 1
                """,
                (repository, pull_request_number),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return _build_publish_decision_record(_postgres_row_mapping(row))

    def list_audit_entries(self, *, entity_type: str, entity_id: str) -> list[AuditLogRecord]:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT entity_type, entity_id, action, actor, timestamp, details
                FROM audit_log
                WHERE entity_type = %s AND entity_id = %s
                ORDER BY timestamp DESC, id DESC
                """,
                (entity_type, entity_id),
            )
            rows = cursor.fetchall()
        return [_build_audit_log_record(_postgres_row_mapping(row)) for row in rows]

    def _record_audit(
        self,
        *,
        entity_type: str,
        entity_id: str,
        action: str,
        actor: str,
        details: dict[str, Any],
    ) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO audit_log (
                    entity_type,
                    entity_id,
                    action,
                    actor,
                    timestamp,
                    details
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    entity_type,
                    entity_id,
                    action,
                    actor,
                    _to_iso(datetime.now(timezone.utc)),  # noqa: UP017
                    _json_dump(details),
                ),
            )
