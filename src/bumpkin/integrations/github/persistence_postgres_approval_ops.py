from __future__ import annotations

from bumpkin.integrations.github.guards import ApprovalRecord
from bumpkin.integrations.github.persistence_audit_payloads import (
    build_approval_deleted_payload as _build_approval_deleted_payload,
)
from bumpkin.integrations.github.persistence_audit_payloads import (
    build_approval_recorded_payload as _build_approval_recorded_payload,
)
from bumpkin.integrations.github.persistence_record_parsing import (
    build_approval_record as _build_approval_record,
)
from bumpkin.integrations.github.persistence_serialization import (
    postgres_row_mapping as _postgres_row_mapping,
)
from bumpkin.integrations.github.persistence_serialization import (
    to_iso as _to_iso,
)


def record_approval(
    self,
    *,
    approval: ApprovalRecord,
    commit_sha: str,
    source_event_id: str | None = None,
) -> int:
    with self._connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO app_approvals (
                repository,
                pull_request_number,
                commit_sha,
                approved_label,
                recommendation_hash,
                approved_by,
                approved_at,
                source_event_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                approval.repository,
                approval.pull_request_number,
                commit_sha,
                approval.approved_label,
                approval.recommendation_hash,
                approval.approved_by,
                _to_iso(approval.approved_at),
                source_event_id,
            ),
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("Postgres did not return id for insert operation.")
    row_map = _postgres_row_mapping(row)
    if row_map["id"] is None:
        raise RuntimeError("Postgres did not return id for insert operation.")
    approval_id = int(row_map["id"])
    self._record_audit(
        **_build_approval_recorded_payload(
            approval_id=approval_id,
            approval=approval,
            commit_sha=commit_sha,
            source_event_id=source_event_id,
        ).as_kwargs(),
    )
    self._connection.commit()
    return approval_id


def latest_approval_for_pr(
    self,
    *,
    repository: str,
    pull_request_number: int,
) -> ApprovalRecord | None:
    with self._connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT repository, pull_request_number, approved_label,
                   recommendation_hash, approved_by, approved_at
            FROM app_approvals
            WHERE repository = %s AND pull_request_number = %s
            ORDER BY approved_at DESC, id DESC
            LIMIT 1
            """,
            (repository, pull_request_number),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return _build_approval_record(_postgres_row_mapping(row))


def delete_approvals(self, *, repository: str, pull_request_number: int) -> int:
    with self._connection.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM app_approvals
            WHERE repository = %s AND pull_request_number = %s
            """,
            (repository, pull_request_number),
        )
        removed = int(cursor.rowcount)
    if removed > 0:
        self._record_audit(
            **_build_approval_deleted_payload(
                repository=repository,
                pull_request_number=pull_request_number,
                removed_rows=removed,
            ).as_kwargs(),
        )
        self._connection.commit()
    return removed


class PostgresApprovalOpsMixin:
    record_approval = record_approval
    latest_approval_for_pr = latest_approval_for_pr
    delete_approvals = delete_approvals
