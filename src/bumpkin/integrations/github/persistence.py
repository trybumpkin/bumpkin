from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any, Self, cast

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - exercised in deployment, optional in local dev
    psycopg = None
    dict_row = None

from bumpkin.integrations.github.guards import ApprovalRecord, PublishGuardDecision
from bumpkin.integrations.github.ingress import AppEventEnvelope
from bumpkin.integrations.github.persistence_migrations import (
    apply_postgres_migrations,
    apply_sqlite_migrations,
)
from bumpkin.integrations.github.persistence_models import (
    AuditLogRecord,
    PublishDecisionRecord,
    RecommendationSnapshot,
    ReleaseBacklogItem,
    StoredEventRecord,
)
from bumpkin.integrations.github.persistence_protocols import (
    DEFAULT_EVENT_STATUS,
    AppStateStore,
)
from bumpkin.integrations.github.persistence_serialization import (
    clean_optional_text as _clean_optional_text,
)
from bumpkin.integrations.github.persistence_serialization import (
    from_iso as _from_iso,
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
    require_lastrowid as _require_lastrowid,
)
from bumpkin.integrations.github.persistence_serialization import (
    to_iso as _to_iso,
)
from bumpkin.integrations.github.types import AppEvent

_PROPOSED_BUMP_RE = re.compile(r"(?im)^proposed bump \(court\):\s*(?P<label>[A-Z_]+)")
_RECOMMENDATION_LINE_RE = re.compile(
    r"(?im)^recommendation\s*:\s*[^\n\rA-Z]*(?P<label>NO[\s_-]?BUMP|MAJOR|MINOR|PATCH)\b"
)
_VALID_BUMP_LABELS = frozenset({"MAJOR", "MINOR", "PATCH", "NO_BUMP"})
_NEXT_VERSION_ARROW_RE = re.compile(
    r"(?im)^next version\s*:\s*(?P<current>v?\d+\.\d+\.\d+)\s*(?:→|->)\s*(?P<next>v?\d+\.\d+\.\d+)\s*$"
)
_NEXT_VERSION_CURRENT_ONLY_RE = re.compile(
    r"(?im)^next version\s*:\s*not computed\s*\(current=(?P<current>v?\d+\.\d+\.\d+)\)\s*$"
)


def _extract_comment_body(payload: dict[str, Any]) -> str:
    comment = payload.get("comment")
    if not isinstance(comment, dict):
        return ""
    body = comment.get("body")
    return str(body).strip() if body is not None else ""


def _extract_recommended_label(comment_body: str) -> str | None:
    match = _PROPOSED_BUMP_RE.search(comment_body)
    if match:
        label = match.group("label").strip().upper()
        if label in _VALID_BUMP_LABELS:
            return label

    match = _RECOMMENDATION_LINE_RE.search(comment_body)
    if not match:
        return None
    label = re.sub(r"[\s\-]+", "_", match.group("label").strip().upper()).strip("_")
    if label == "NOBUMP":
        label = "NO_BUMP"
    if label in _VALID_BUMP_LABELS:
        return label
    return None


def _normalize_semver_token(token: str) -> str | None:
    normalized = token.strip()
    if not re.match(r"^v?\d+\.\d+\.\d+$", normalized):
        return None
    normalized = normalized.removeprefix("v")
    major, minor, patch = normalized.split(".")
    return f"{int(major)}.{int(minor)}.{int(patch)}"


def _extract_recommended_current_version(comment_body: str) -> str | None:
    arrow_match = _NEXT_VERSION_ARROW_RE.search(comment_body)
    if arrow_match:
        return _normalize_semver_token(arrow_match.group("current"))

    current_only_match = _NEXT_VERSION_CURRENT_ONLY_RE.search(comment_body)
    if current_only_match:
        return _normalize_semver_token(current_only_match.group("current"))
    return None


class SqliteAppStateStore:
    def __init__(self, db_path: str | Path) -> None:
        path = Path(db_path).expanduser()
        self._connection = sqlite3.connect(path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        apply_sqlite_migrations(self._connection)

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
            self._connection.execute(
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
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        except sqlite3.IntegrityError:
            return False

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
        cursor = self._connection.execute(
            """
            SELECT provider, provider_event_id, event_type, action, repository,
                   pull_request_number, sender_login, received_at, payload,
                   payload_hash, headers_hash, status
            FROM app_events
            WHERE provider = ? AND provider_event_id = ?
            LIMIT 1
            """,
            (provider, provider_event_id),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return StoredEventRecord(
            provider=str(row["provider"]),
            provider_event_id=str(row["provider_event_id"]),
            event_type=str(row["event_type"]),
            action=str(row["action"]) if row["action"] is not None else None,
            repository=str(row["repository"]) if row["repository"] is not None else None,
            pull_request_number=int(row["pull_request_number"])
            if row["pull_request_number"] is not None
            else None,
            sender_login=str(row["sender_login"]) if row["sender_login"] is not None else None,
            received_at=_from_iso(str(row["received_at"])),
            payload=json.loads(str(row["payload"])),
            payload_hash=str(row["payload_hash"]),
            headers_hash=str(row["headers_hash"]),
            status=str(row["status"]),
        )

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
        cursor = self._connection.execute(
            """
            UPDATE app_events
            SET status = ?
            WHERE provider = ? AND provider_event_id = ?
            """,
            (normalized_status, provider, provider_event_id),
        )
        updated = int(cursor.rowcount)
        if updated <= 0:
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
        cursor = self._connection.execute(
            """
            SELECT e.provider, e.provider_event_id, e.event_type, e.action, e.repository,
                   e.pull_request_number, e.sender_login, e.received_at, e.payload,
                   e.payload_hash, e.headers_hash, e.status
            FROM app_events AS e
            LEFT JOIN app_recommendations AS r
              ON r.source_event_id = e.provider_event_id
            WHERE e.provider = ?
              AND e.repository = ?
              AND e.event_type = 'pull_request'
              AND e.action = 'closed'
              AND e.status LIKE 'deferred_deploy:%'
              AND r.source_event_id IS NULL
            ORDER BY e.received_at ASC, e.id ASC
            LIMIT ?
            """,
            (provider, repository, max(1, int(limit))),
        )
        rows = cursor.fetchall()
        return [
            StoredEventRecord(
                provider=str(row["provider"]),
                provider_event_id=str(row["provider_event_id"]),
                event_type=str(row["event_type"]),
                action=str(row["action"]) if row["action"] is not None else None,
                repository=str(row["repository"]) if row["repository"] is not None else None,
                pull_request_number=int(row["pull_request_number"])
                if row["pull_request_number"] is not None
                else None,
                sender_login=str(row["sender_login"]) if row["sender_login"] is not None else None,
                received_at=_from_iso(str(row["received_at"])),
                payload=json.loads(str(row["payload"])),
                payload_hash=str(row["payload_hash"]),
                headers_hash=str(row["headers_hash"]),
                status=str(row["status"]),
            )
            for row in rows
        ]

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
        snapshot_cursor = self._connection.execute(
            """
            SELECT label, current_version
            FROM app_recommendations
            WHERE repository = ?
              AND pull_request_number = ?
            ORDER BY recorded_at DESC, id DESC
            LIMIT 1
            """,
            (repository, pull_request_number),
        )
        snapshot_row = snapshot_cursor.fetchone()
        if snapshot_row is not None:
            label = str(snapshot_row["label"]).strip().upper()
            current_version = (
                _normalize_semver_token(str(snapshot_row["current_version"]))
                if snapshot_row["current_version"] is not None
                else None
            )
            return RecommendationSnapshot(
                label=label,
                current_version=current_version,
            )

        cursor = self._connection.execute(
            """
            SELECT payload
            FROM app_events
            WHERE repository = ?
              AND pull_request_number = ?
              AND event_type = 'issue_comment'
            ORDER BY received_at DESC, id DESC
            LIMIT 250
            """,
            (repository, pull_request_number),
        )
        for row in cursor:
            raw_payload = str(row["payload"])
            payload = json.loads(raw_payload)
            if not isinstance(payload, dict):
                continue
            body = _extract_comment_body(payload)
            if not body:
                continue
            label = _extract_recommended_label(body)
            if label is not None:
                current_version = _extract_recommended_current_version(body)
                return RecommendationSnapshot(
                    label=label,
                    current_version=current_version,
                )
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
        self._connection.execute(
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
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(repository, pull_request_number)
            DO UPDATE SET
                label = excluded.label,
                current_version = excluded.current_version,
                source = excluded.source,
                source_event_id = excluded.source_event_id,
                recorded_at = excluded.recorded_at
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
        self._connection.execute(
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
            ON CONFLICT(repository, pull_request_number)
            DO UPDATE SET
                merge_commit_sha = excluded.merge_commit_sha,
                recommended_label = excluded.recommended_label,
                recommended_current_version = excluded.recommended_current_version,
                pull_request_title = excluded.pull_request_title,
                pull_request_author_login = excluded.pull_request_author_login,
                pull_request_url = excluded.pull_request_url,
                release_summary = excluded.release_summary,
                source_event_id = excluded.source_event_id,
                merged_at = excluded.merged_at,
                updated_at = CURRENT_TIMESTAMP
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
        row = self._connection.execute(
            """
            SELECT id
            FROM app_release_backlog
            WHERE repository = ? AND pull_request_number = ?
            LIMIT 1
            """,
            (normalized_repository, pull_request_number),
        ).fetchone()
        if row is None:
            raise RuntimeError("Release backlog item upsert succeeded but no row was returned.")
        backlog_id = int(row["id"])
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
        cursor = self._connection.execute(
            """
            SELECT id, repository, pull_request_number, merge_commit_sha,
                   recommended_label, recommended_current_version,
                   pull_request_title, pull_request_author_login, pull_request_url,
                   release_summary, source_event_id,
                   merged_at, included_in_release_tag, included_at
            FROM app_release_backlog
            WHERE repository = ?
              AND included_in_release_tag IS NULL
            ORDER BY merged_at ASC, id ASC
            LIMIT ?
            """,
            (normalized_repository, max(1, int(limit))),
        )
        rows = cursor.fetchall()
        return [
            ReleaseBacklogItem(
                id=int(row["id"]),
                repository=str(row["repository"]),
                pull_request_number=int(row["pull_request_number"]),
                merge_commit_sha=str(row["merge_commit_sha"]),
                recommended_label=str(row["recommended_label"]),
                recommended_current_version=(
                    _normalize_semver_token(str(row["recommended_current_version"]))
                    if row["recommended_current_version"] is not None
                    else None
                ),
                pull_request_title=str(row["pull_request_title"])
                if row["pull_request_title"] is not None
                else None,
                pull_request_author_login=str(row["pull_request_author_login"])
                if row["pull_request_author_login"] is not None
                else None,
                pull_request_url=str(row["pull_request_url"])
                if row["pull_request_url"] is not None
                else None,
                release_summary=str(row["release_summary"])
                if row["release_summary"] is not None
                else None,
                source_event_id=str(row["source_event_id"])
                if row["source_event_id"] is not None
                else None,
                merged_at=_from_iso(str(row["merged_at"])),
                included_in_release_tag=str(row["included_in_release_tag"])
                if row["included_in_release_tag"] is not None
                else None,
                included_at=_from_iso(str(row["included_at"]))
                if row["included_at"] is not None
                else None,
            )
            for row in rows
        ]

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
        updated_count = 0
        for backlog_id in normalized_ids:
            cursor = self._connection.execute(
                """
                UPDATE app_release_backlog
                SET included_in_release_tag = ?,
                    included_at = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE repository = ?
                  AND id = ?
                  AND included_in_release_tag IS NULL
                """,
                (
                    normalized_release_tag,
                    normalized_included_at,
                    normalized_repository,
                    backlog_id,
                ),
            )
            updated_count += int(cursor.rowcount or 0)
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
        cursor = self._connection.execute(
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
        approval_id = _require_lastrowid(cursor)
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
        cursor = self._connection.execute(
            """
            SELECT repository, pull_request_number, approved_label,
                   recommendation_hash, approved_by, approved_at
            FROM app_approvals
            WHERE repository = ? AND pull_request_number = ?
            ORDER BY approved_at DESC, id DESC
            LIMIT 1
            """,
            (repository, pull_request_number),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return ApprovalRecord(
            repository=str(row["repository"]),
            pull_request_number=int(row["pull_request_number"]),
            approved_label=str(row["approved_label"]),
            recommendation_hash=str(row["recommendation_hash"]),
            approved_by=str(row["approved_by"]),
            approved_at=_from_iso(str(row["approved_at"])),
        )

    def delete_approvals(self, *, repository: str, pull_request_number: int) -> int:
        cursor = self._connection.execute(
            """
            DELETE FROM app_approvals
            WHERE repository = ? AND pull_request_number = ?
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
        cursor = self._connection.execute(
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                repository,
                pull_request_number,
                commit_sha,
                1 if decision.allowed else 0,
                reason,
                _json_dump({"guard_reasons": guard_reasons}),
                _to_iso(normalized_evaluated_at),
                _json_dump(policy_snapshot),
            ),
        )
        decision_id = _require_lastrowid(cursor)
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
        cursor = self._connection.execute(
            """
            SELECT repository, pull_request_number, commit_sha, allowed, reason,
                   guard_reasons, evaluated_at, policy_snapshot
            FROM publish_decisions
            WHERE repository = ? AND pull_request_number = ?
            ORDER BY evaluated_at DESC, id DESC
            LIMIT 1
            """,
            (repository, pull_request_number),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        guard_reasons_payload = json.loads(str(row["guard_reasons"]))
        guard_reasons_raw = guard_reasons_payload.get("guard_reasons", [])
        guard_reasons = tuple(
            item for item in guard_reasons_raw if isinstance(item, str) and item.strip()
        )
        return PublishDecisionRecord(
            repository=str(row["repository"]),
            pull_request_number=int(row["pull_request_number"]),
            commit_sha=str(row["commit_sha"]),
            allowed=bool(row["allowed"]),
            reason=str(row["reason"]),
            guard_reasons=guard_reasons,
            evaluated_at=_from_iso(str(row["evaluated_at"])),
            policy_snapshot=json.loads(str(row["policy_snapshot"])),
        )

    def list_audit_entries(self, *, entity_type: str, entity_id: str) -> list[AuditLogRecord]:
        cursor = self._connection.execute(
            """
            SELECT entity_type, entity_id, action, actor, timestamp, details
            FROM audit_log
            WHERE entity_type = ? AND entity_id = ?
            ORDER BY timestamp DESC, id DESC
            """,
            (entity_type, entity_id),
        )
        rows = cursor.fetchall()
        return [
            AuditLogRecord(
                entity_type=str(row["entity_type"]),
                entity_id=str(row["entity_id"]),
                action=str(row["action"]),
                actor=str(row["actor"]),
                timestamp=_from_iso(str(row["timestamp"])),
                details=json.loads(str(row["details"])),
            )
            for row in rows
        ]

    def _record_audit(
        self,
        *,
        entity_type: str,
        entity_id: str,
        action: str,
        actor: str,
        details: dict[str, Any],
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO audit_log (
                entity_type,
                entity_id,
                action,
                actor,
                timestamp,
                details
            )
            VALUES (?, ?, ?, ?, ?, ?)
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
        return StoredEventRecord(
            provider=str(row_map["provider"]),
            provider_event_id=str(row_map["provider_event_id"]),
            event_type=str(row_map["event_type"]),
            action=str(row_map["action"]) if row_map["action"] is not None else None,
            repository=str(row_map["repository"]) if row_map["repository"] is not None else None,
            pull_request_number=int(row_map["pull_request_number"])
            if row_map["pull_request_number"] is not None
            else None,
            sender_login=str(row_map["sender_login"])
            if row_map["sender_login"] is not None
            else None,
            received_at=_from_iso(str(row_map["received_at"])),
            payload=json.loads(str(row_map["payload"])),
            payload_hash=str(row_map["payload_hash"]),
            headers_hash=str(row_map["headers_hash"]),
            status=str(row_map["status"]),
        )

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
        return [
            StoredEventRecord(
                provider=str(row_map["provider"]),
                provider_event_id=str(row_map["provider_event_id"]),
                event_type=str(row_map["event_type"]),
                action=str(row_map["action"]) if row_map["action"] is not None else None,
                repository=str(row_map["repository"])
                if row_map["repository"] is not None
                else None,
                pull_request_number=int(row_map["pull_request_number"])
                if row_map["pull_request_number"] is not None
                else None,
                sender_login=str(row_map["sender_login"])
                if row_map["sender_login"] is not None
                else None,
                received_at=_from_iso(str(row_map["received_at"])),
                payload=json.loads(str(row_map["payload"])),
                payload_hash=str(row_map["payload_hash"]),
                headers_hash=str(row_map["headers_hash"]),
                status=str(row_map["status"]),
            )
            for row_map in (_postgres_row_mapping(row) for row in rows)
        ]

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
            snapshot_map = _postgres_row_mapping(snapshot_row)
            label = str(snapshot_map["label"]).strip().upper()
            current_version = (
                _normalize_semver_token(str(snapshot_map["current_version"]))
                if snapshot_map["current_version"] is not None
                else None
            )
            return RecommendationSnapshot(label=label, current_version=current_version)

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
            if not isinstance(payload, dict):
                continue
            body = _extract_comment_body(payload)
            if not body:
                continue
            label = _extract_recommended_label(body)
            if label is not None:
                current_version = _extract_recommended_current_version(body)
                return RecommendationSnapshot(label=label, current_version=current_version)
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
        return [
            ReleaseBacklogItem(
                id=int(row_map["id"]),
                repository=str(row_map["repository"]),
                pull_request_number=int(row_map["pull_request_number"]),
                merge_commit_sha=str(row_map["merge_commit_sha"]),
                recommended_label=str(row_map["recommended_label"]),
                recommended_current_version=(
                    _normalize_semver_token(str(row_map["recommended_current_version"]))
                    if row_map["recommended_current_version"] is not None
                    else None
                ),
                pull_request_title=str(row_map["pull_request_title"])
                if row_map["pull_request_title"] is not None
                else None,
                pull_request_author_login=str(row_map["pull_request_author_login"])
                if row_map["pull_request_author_login"] is not None
                else None,
                pull_request_url=str(row_map["pull_request_url"])
                if row_map["pull_request_url"] is not None
                else None,
                release_summary=str(row_map["release_summary"])
                if row_map["release_summary"] is not None
                else None,
                source_event_id=str(row_map["source_event_id"])
                if row_map["source_event_id"] is not None
                else None,
                merged_at=_from_iso(str(row_map["merged_at"])),
                included_in_release_tag=str(row_map["included_in_release_tag"])
                if row_map["included_in_release_tag"] is not None
                else None,
                included_at=_from_iso(str(row_map["included_at"]))
                if row_map["included_at"] is not None
                else None,
            )
            for row_map in (_postgres_row_mapping(row) for row in rows)
        ]

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
        row_map = _postgres_row_mapping(row)
        return ApprovalRecord(
            repository=str(row_map["repository"]),
            pull_request_number=int(row_map["pull_request_number"]),
            approved_label=str(row_map["approved_label"]),
            recommendation_hash=str(row_map["recommendation_hash"]),
            approved_by=str(row_map["approved_by"]),
            approved_at=_from_iso(str(row_map["approved_at"])),
        )

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
        row_map = _postgres_row_mapping(row)
        guard_reasons_payload = json.loads(str(row_map["guard_reasons"]))
        guard_reasons_raw = guard_reasons_payload.get("guard_reasons", [])
        guard_reasons = tuple(
            item for item in guard_reasons_raw if isinstance(item, str) and item.strip()
        )
        return PublishDecisionRecord(
            repository=str(row_map["repository"]),
            pull_request_number=int(row_map["pull_request_number"]),
            commit_sha=str(row_map["commit_sha"]),
            allowed=bool(row_map["allowed"]),
            reason=str(row_map["reason"]),
            guard_reasons=guard_reasons,
            evaluated_at=_from_iso(str(row_map["evaluated_at"])),
            policy_snapshot=json.loads(str(row_map["policy_snapshot"])),
        )

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
        return [
            AuditLogRecord(
                entity_type=str(row_map["entity_type"]),
                entity_id=str(row_map["entity_id"]),
                action=str(row_map["action"]),
                actor=str(row_map["actor"]),
                timestamp=_from_iso(str(row_map["timestamp"])),
                details=json.loads(str(row_map["details"])),
            )
            for row_map in (_postgres_row_mapping(row) for row in rows)
        ]

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


class EphemeralAppStateStore:
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
        del source, source_event_id, recorded_at
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
        del approval, commit_sha, source_event_id
        return 0

    def latest_approval_for_pr(
        self,
        *,
        repository: str,
        pull_request_number: int,
    ) -> ApprovalRecord | None:
        del repository, pull_request_number
        return None

    def delete_approvals(self, *, repository: str, pull_request_number: int) -> int:
        del repository, pull_request_number
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
        del repository, pull_request_number, commit_sha, decision, policy_snapshot, evaluated_at
        return 0

    def latest_publish_decision_for_pr(
        self,
        *,
        repository: str,
        pull_request_number: int,
    ) -> PublishDecisionRecord | None:
        del repository, pull_request_number
        return None

    def list_audit_entries(self, *, entity_type: str, entity_id: str) -> list[AuditLogRecord]:
        del entity_type, entity_id
        return []


def build_app_state_store(*, db_path: str | Path | None, database_url: str | None) -> AppStateStore:
    if database_url is not None and database_url.strip():
        return PostgresAppStateStore(database_url.strip())
    if db_path is None:
        raise ValueError("Either db_path or database_url is required.")
    return SqliteAppStateStore(db_path)


class SqliteApprovalStore:
    def __init__(self, state_store: AppStateStore) -> None:
        self._state_store = state_store

    def get(self, repository: str, pull_request_number: int) -> ApprovalRecord | None:
        return self._state_store.latest_approval_for_pr(
            repository=repository,
            pull_request_number=pull_request_number,
        )

    def put(
        self,
        approval: ApprovalRecord,
        *,
        commit_sha: str,
        source_event_id: str | None = None,
    ) -> int:
        return self._state_store.record_approval(
            approval=approval,
            commit_sha=commit_sha,
            source_event_id=source_event_id,
        )

    def delete(self, repository: str, pull_request_number: int) -> int:
        return self._state_store.delete_approvals(
            repository=repository,
            pull_request_number=pull_request_number,
        )
