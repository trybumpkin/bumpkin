from __future__ import annotations

import json
from collections.abc import Mapping
from hashlib import sha256

from bumpkin.integrations.github.guards import ApprovalRecord
from bumpkin.integrations.github.persistence_protocols import ApprovalPersistenceStore

__all__ = [
    "InMemoryApprovalStore",
    "SqliteApprovalStore",
    "compute_recommendation_hash",
]


class InMemoryApprovalStore:
    def __init__(self) -> None:
        self._records: dict[tuple[str, int], ApprovalRecord] = {}

    def get(self, repository: str, pull_request_number: int) -> ApprovalRecord | None:
        key = (repository.strip(), int(pull_request_number))
        return self._records.get(key)

    def put(self, approval: ApprovalRecord) -> None:
        key = (approval.repository.strip(), int(approval.pull_request_number))
        self._records[key] = approval

    def delete(self, repository: str, pull_request_number: int) -> None:
        key = (repository.strip(), int(pull_request_number))
        self._records.pop(key, None)


class SqliteApprovalStore:
    def __init__(self, state_store: ApprovalPersistenceStore) -> None:
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


def compute_recommendation_hash(payload: Mapping[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()
