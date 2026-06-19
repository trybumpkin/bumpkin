from __future__ import annotations

from pathlib import Path

from bumpkin.integrations.github.persistence_postgres import PostgresAppStateStore
from bumpkin.integrations.github.persistence_protocols import AppStateStore
from bumpkin.integrations.github.persistence_sqlite import SqliteAppStateStore


def build_app_state_store(*, db_path: str | Path | None, database_url: str | None) -> AppStateStore:
    if database_url is not None and database_url.strip():
        return PostgresAppStateStore(database_url.strip())
    if db_path is None:
        raise ValueError("Either db_path or database_url is required.")
    return SqliteAppStateStore(db_path)
