from __future__ import annotations

from pathlib import Path

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


class SqliteApprovalStore:
    def __init__(self, state_store: AppStateStore) -> None:
        self._state_store = state_store

    def get(self, repository: str, pull_request_number: int) -> ApprovalRecord | None:
        return self._state_store.latest_approval_for_pr(
            repository=repository,
            pull_request_number=pull_request_number,
        )

    def put(
        self,
        approval: ApprovalRecord,
        *,
        commit_sha: str,
        source_event_id: str | None = None,
    ) -> int:
        return self._state_store.record_approval(
            approval=approval,
            commit_sha=commit_sha,
            source_event_id=source_event_id,
        )

    def delete(self, repository: str, pull_request_number: int) -> int:
        return self._state_store.delete_approvals(
            repository=repository,
            pull_request_number=pull_request_number,
        )
