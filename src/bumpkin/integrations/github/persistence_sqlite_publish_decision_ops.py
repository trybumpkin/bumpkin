from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bumpkin.integrations.github.guards import PublishGuardDecision
from bumpkin.integrations.github.persistence_audit_payloads import (
    build_publish_decision_recorded_payload as _build_publish_decision_recorded_payload,
)
from bumpkin.integrations.github.persistence_serialization import (
    json_dump as _json_dump,
)
from bumpkin.integrations.github.persistence_serialization import (
    normalize_timestamp as _normalize_timestamp,
)
from bumpkin.integrations.github.persistence_serialization import (
    require_lastrowid as _require_lastrowid,
)
from bumpkin.integrations.github.persistence_serialization import (
    to_iso as _to_iso,
)
from bumpkin.integrations.github.persistence_sqlite_support import SqliteStoreSupport


class SqlitePublishDecisionOpsMixin(SqliteStoreSupport):
    def record_publish_decision(
        self,
        *,
        repository: str,
        pull_request_number: int,
        commit_sha: str,
        decision: PublishGuardDecision,
        policy_snapshot: dict[str, Any],
        evaluated_at: datetime | None = None,
    ) -> int:
        normalized_evaluated_at = _normalize_timestamp(
            evaluated_at or datetime.now(timezone.utc),  # noqa: UP017
        )
        guard_reasons = list(decision.guard_reasons)
        reason = guard_reasons[0] if guard_reasons else "allowed"
        cursor = self._connection.execute(
            """
            INSERT INTO publish_decisions (
                repository, pull_request_number, commit_sha, allowed, reason,
                guard_reasons, evaluated_at, policy_snapshot
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                repository,
                pull_request_number,
                commit_sha,
                1 if decision.allowed else 0,
                reason,
                _json_dump({"guard_reasons": guard_reasons}),
                _to_iso(normalized_evaluated_at),
                _json_dump(policy_snapshot),
            ),
        )
        decision_id = _require_lastrowid(cursor)
        self._record_audit(
            **_build_publish_decision_recorded_payload(
                decision_id=decision_id,
                repository=repository,
                pull_request_number=pull_request_number,
                commit_sha=commit_sha,
                decision=decision,
            ).as_kwargs(),
        )
        self._connection.commit()
        return decision_id
