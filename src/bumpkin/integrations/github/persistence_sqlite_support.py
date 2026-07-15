from __future__ import annotations

import sqlite3
from typing import Any


class SqliteStoreSupport:
    _connection: sqlite3.Connection

    def _record_audit(
        self,
        *,
        entity_type: str,
        entity_id: str,
        action: str,
        actor: str,
        details: dict[str, Any],
    ) -> None:
        raise NotImplementedError
