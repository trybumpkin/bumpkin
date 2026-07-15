from __future__ import annotations

from bumpkin.integrations.github.persistence_models import AuditLogRecord
from bumpkin.integrations.github.persistence_record_parsing import (
    build_audit_log_record as _build_audit_log_record,
)
from bumpkin.integrations.github.persistence_sqlite_support import SqliteStoreSupport


class SqliteAuditOpsMixin(SqliteStoreSupport):
    def list_audit_entries(self, *, entity_type: str, entity_id: str) -> list[AuditLogRecord]:
        rows = self._connection.execute(
            """
            SELECT entity_type, entity_id, action, actor, timestamp, details
            FROM audit_log
            WHERE entity_type = ? AND entity_id = ?
            ORDER BY timestamp DESC, id DESC
            """,
            (entity_type, entity_id),
        ).fetchall()
        return [_build_audit_log_record(dict(row)) for row in rows]
