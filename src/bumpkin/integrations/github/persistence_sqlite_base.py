from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Self

from bumpkin.integrations.github.persistence_migrations import apply_sqlite_migrations
from bumpkin.integrations.github.persistence_serialization import json_dump as _json_dump
from bumpkin.integrations.github.persistence_serialization import to_iso as _to_iso
from bumpkin.integrations.github.persistence_sqlite_support import SqliteStoreSupport


class SqliteConnectionMixin(SqliteStoreSupport):
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
                entity_type, entity_id, action, actor, timestamp, details
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
