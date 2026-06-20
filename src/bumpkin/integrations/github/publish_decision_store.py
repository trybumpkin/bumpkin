from __future__ import annotations

from datetime import datetime
from typing import Any

from bumpkin.integrations.github.guards import PublishGuardDecision
from bumpkin.integrations.github.persistence_models import PublishDecisionRecord
from bumpkin.integrations.github.persistence_protocols import PublishDecisionPersistenceStore

__all__ = ["SqlitePublishDecisionStore"]


class SqlitePublishDecisionStore:
    def __init__(self, state_store: PublishDecisionPersistenceStore) -> None:
        self._state_store = state_store

    def record(
        self,
        *,
        repository: str,
        pull_request_number: int,
        commit_sha: str,
        decision: PublishGuardDecision,
        policy_snapshot: dict[str, Any],
        evaluated_at: datetime | None = None,
    ) -> int:
        return self._state_store.record_publish_decision(
            repository=repository,
            pull_request_number=pull_request_number,
            commit_sha=commit_sha,
            decision=decision,
            policy_snapshot=policy_snapshot,
            evaluated_at=evaluated_at,
        )

    def latest_for_pr(
        self,
        *,
        repository: str,
        pull_request_number: int,
    ) -> PublishDecisionRecord | None:
        return self._state_store.latest_publish_decision_for_pr(
            repository=repository,
            pull_request_number=pull_request_number,
        )
