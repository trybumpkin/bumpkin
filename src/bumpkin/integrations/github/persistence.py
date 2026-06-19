from __future__ import annotations

from pathlib import Path

from bumpkin.integrations.github.approval_store import SqliteApprovalStore
from bumpkin.integrations.github.guards import ApprovalRecord, PublishGuardDecision
from bumpkin.integrations.github.persistence_ephemeral import EphemeralAppStateStore
from bumpkin.integrations.github.persistence_factory import (
    build_app_state_store as _build_app_state_store,
)
from bumpkin.integrations.github.persistence_models import ReleaseBacklogItem
from bumpkin.integrations.github.persistence_postgres import PostgresAppStateStore
from bumpkin.integrations.github.persistence_protocols import AppStateStore
from bumpkin.integrations.github.persistence_sqlite import SqliteAppStateStore

__all__ = [
    "AppStateStore",
    "ApprovalRecord",
    "EphemeralAppStateStore",
    "PostgresAppStateStore",
    "PublishGuardDecision",
    "ReleaseBacklogItem",
    "SqliteAppStateStore",
    "SqliteApprovalStore",
    "build_app_state_store",
]


def build_app_state_store(
    *,
    db_path: str | Path | None = None,
    database_url: str | None,
) -> AppStateStore:
    return _build_app_state_store(db_path=db_path, database_url=database_url)
