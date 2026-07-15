from __future__ import annotations

import sqlite3

from bumpkin.integrations.github.ingress import AppEventEnvelope
from bumpkin.integrations.github.persistence_audit_payloads import (
    build_event_recorded_payload as _build_event_recorded_payload,
)
from bumpkin.integrations.github.persistence_audit_payloads import (
    build_event_status_updated_payload as _build_event_status_updated_payload,
)
from bumpkin.integrations.github.persistence_models import StoredEventRecord
from bumpkin.integrations.github.persistence_protocols import DEFAULT_EVENT_STATUS
from bumpkin.integrations.github.persistence_record_parsing import (
    build_stored_event_record as _build_stored_event_record,
)
from bumpkin.integrations.github.persistence_serialization import json_dump as _json_dump
from bumpkin.integrations.github.persistence_serialization import to_iso as _to_iso
from bumpkin.integrations.github.persistence_sqlite_support import SqliteStoreSupport
from bumpkin.integrations.github.types import AppEvent


class SqliteEventOpsMixin(SqliteStoreSupport):
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
                    provider, provider_event_id, event_type, action, repository,
                    pull_request_number, sender_login, received_at, payload,
                    payload_hash, headers_hash, status
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
            **_build_event_recorded_payload(
                provider=envelope.source,
                provider_event_id=envelope.event_id,
                event=event,
                status=status,
            ).as_kwargs(),
        )
        self._connection.commit()
        return True

    def get_event(self, *, provider: str, provider_event_id: str) -> StoredEventRecord | None:
        row = self._connection.execute(
            """
            SELECT provider, provider_event_id, event_type, action, repository,
                   pull_request_number, sender_login, received_at, payload,
                   payload_hash, headers_hash, status
            FROM app_events
            WHERE provider = ? AND provider_event_id = ?
            LIMIT 1
            """,
            (provider, provider_event_id),
        ).fetchone()
        return _build_stored_event_record(dict(row)) if row is not None else None

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
            UPDATE app_events SET status = ?
            WHERE provider = ? AND provider_event_id = ?
            """,
            (normalized_status, provider, provider_event_id),
        )
        if int(cursor.rowcount) <= 0:
            return False
        self._record_audit(
            **_build_event_status_updated_payload(
                provider=provider,
                provider_event_id=provider_event_id,
                status=normalized_status,
            ).as_kwargs(),
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
        rows = self._connection.execute(
            """
            SELECT e.provider, e.provider_event_id, e.event_type, e.action, e.repository,
                   e.pull_request_number, e.sender_login, e.received_at, e.payload,
                   e.payload_hash, e.headers_hash, e.status
            FROM app_events AS e
            LEFT JOIN app_recommendations AS r ON r.source_event_id = e.provider_event_id
            WHERE e.provider = ? AND e.repository = ?
              AND e.event_type = 'pull_request' AND e.action = 'closed'
              AND e.status LIKE 'deferred_deploy:%' AND r.source_event_id IS NULL
            ORDER BY e.received_at ASC, e.id ASC LIMIT ?
            """,
            (provider, repository, max(1, int(limit))),
        ).fetchall()
        return [_build_stored_event_record(dict(row)) for row in rows]
