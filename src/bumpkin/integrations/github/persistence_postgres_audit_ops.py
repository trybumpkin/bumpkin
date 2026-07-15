from __future__ import annotations

from bumpkin.integrations.github.persistence_models import AuditLogRecord
from bumpkin.integrations.github.persistence_record_parsing import (
    build_audit_log_record as _build_audit_log_record,
)
from bumpkin.integrations.github.persistence_serialization import (
    postgres_row_mapping as _postgres_row_mapping,
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
    return [_build_audit_log_record(_postgres_row_mapping(row)) for row in rows]


class PostgresAuditOpsMixin:
    list_audit_entries = list_audit_entries
