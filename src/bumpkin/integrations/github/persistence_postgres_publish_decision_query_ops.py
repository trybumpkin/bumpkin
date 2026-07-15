from __future__ import annotations

from bumpkin.integrations.github.persistence_models import PublishDecisionRecord
from bumpkin.integrations.github.persistence_record_parsing import (
    build_publish_decision_record as _build_publish_decision_record,
)
from bumpkin.integrations.github.persistence_serialization import (
    postgres_row_mapping as _postgres_row_mapping,
)


def latest_publish_decision_for_pr(
    self,
    *,
    repository: str,
    pull_request_number: int,
) -> PublishDecisionRecord | None:
    with self._connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT repository, pull_request_number, commit_sha, allowed, reason,
                   guard_reasons, evaluated_at, policy_snapshot
            FROM publish_decisions
            WHERE repository = %s AND pull_request_number = %s
            ORDER BY evaluated_at DESC, id DESC
            LIMIT 1
            """,
            (repository, pull_request_number),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return _build_publish_decision_record(_postgres_row_mapping(row))


class PostgresPublishDecisionQueryOpsMixin:
    latest_publish_decision_for_pr = latest_publish_decision_for_pr
