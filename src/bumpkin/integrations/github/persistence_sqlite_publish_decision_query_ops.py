from __future__ import annotations

from bumpkin.integrations.github.persistence_models import PublishDecisionRecord
from bumpkin.integrations.github.persistence_record_parsing import (
    build_publish_decision_record as _build_publish_decision_record,
)
from bumpkin.integrations.github.persistence_sqlite_support import SqliteStoreSupport


class SqlitePublishDecisionQueryOpsMixin(SqliteStoreSupport):
    def latest_publish_decision_for_pr(
        self,
        *,
        repository: str,
        pull_request_number: int,
    ) -> PublishDecisionRecord | None:
        row = self._connection.execute(
            """
            SELECT repository, pull_request_number, commit_sha, allowed,
                   reason, guard_reasons, evaluated_at, policy_snapshot
            FROM publish_decisions
            WHERE repository = ? AND pull_request_number = ?
            ORDER BY evaluated_at DESC, id DESC
            LIMIT 1
            """,
            (repository, pull_request_number),
        ).fetchone()
        return _build_publish_decision_record(dict(row)) if row is not None else None
