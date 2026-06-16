from __future__ import annotations

import json
from collections.abc import Mapping
from hashlib import sha256

from bumpkin.integrations.github.guards import ApprovalRecord


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


def compute_recommendation_hash(payload: Mapping[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()
