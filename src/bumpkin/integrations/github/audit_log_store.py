from __future__ import annotations

from bumpkin.integrations.github.persistence_models import AuditLogRecord
from bumpkin.integrations.github.persistence_protocols import (
    AuditLogStore as AuditLogPersistenceStore,
)

__all__ = ["SqliteAuditLogStore"]


class SqliteAuditLogStore:
    def __init__(self, state_store: AuditLogPersistenceStore) -> None:
        self._state_store = state_store

    def list_entries(self, *, entity_type: str, entity_id: str) -> list[AuditLogRecord]:
        return self._state_store.list_audit_entries(
            entity_type=entity_type,
            entity_id=entity_id,
        )
