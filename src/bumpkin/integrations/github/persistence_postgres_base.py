from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Self, cast

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - exercised in deployment, optional in local dev
    psycopg = None
    dict_row = None

from bumpkin.integrations.github.persistence_migrations import apply_postgres_migrations
from bumpkin.integrations.github.persistence_serialization import (
    json_dump as _json_dump,
)
from bumpkin.integrations.github.persistence_serialization import (
    to_iso as _to_iso,
)


class PostgresConnectionMixin:
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
