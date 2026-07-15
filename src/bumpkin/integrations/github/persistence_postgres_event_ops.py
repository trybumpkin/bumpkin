from __future__ import annotations

try:
    import psycopg
except ImportError:  # pragma: no cover - optional in local dev
    psycopg = None

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
from bumpkin.integrations.github.persistence_serialization import (
    json_dump as _json_dump,
)
from bumpkin.integrations.github.persistence_serialization import (
    postgres_row_mapping as _postgres_row_mapping,
)
from bumpkin.integrations.github.persistence_serialization import (
    to_iso as _to_iso,
)
from bumpkin.integrations.github.types import AppEvent


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
        **_build_event_recorded_payload(
            provider=envelope.source,
            provider_event_id=envelope.event_id,
            event=event,
            status=status,
        ).as_kwargs(),
    )
    self._connection.commit()
    return True


def get_event(
    self,
    *,
    provider: str,
    provider_event_id: str,
) -> StoredEventRecord | None:
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


class PostgresEventOpsMixin:
    record_event = record_event
    get_event = get_event
    update_event_status = update_event_status
    list_deferred_merge_events = list_deferred_merge_events
