from __future__ import annotations

from datetime import datetime

from bumpkin.integrations.github.persistence_audit_payloads import (
    build_release_backlog_included_payload as _build_release_backlog_included_payload,
)
from bumpkin.integrations.github.persistence_audit_payloads import (
    build_release_backlog_upserted_payload as _build_release_backlog_upserted_payload,
)
from bumpkin.integrations.github.persistence_models import ReleaseBacklogItem
from bumpkin.integrations.github.persistence_record_parsing import (
    build_release_backlog_item as _build_release_backlog_item,
)
from bumpkin.integrations.github.persistence_serialization import (
    postgres_row_mapping as _postgres_row_mapping,
)
from bumpkin.integrations.github.persistence_write_normalization import (
    normalize_release_backlog_inclusion_input as _normalize_release_backlog_inclusion_input,
)
from bumpkin.integrations.github.persistence_write_normalization import (
    normalize_release_backlog_write_input as _normalize_release_backlog_write_input,
)


def upsert_release_backlog_item(
    self,
    *,
    repository: str,
    pull_request_number: int,
    merge_commit_sha: str,
    recommended_label: str,
    recommended_current_version: str | None,
    pull_request_title: str | None = None,
    pull_request_author_login: str | None = None,
    pull_request_url: str | None = None,
    release_summary: str | None = None,
    source_event_id: str | None = None,
    merged_at: datetime | None = None,
) -> int:
    normalized = _normalize_release_backlog_write_input(
        repository=repository,
        pull_request_number=pull_request_number,
        merge_commit_sha=merge_commit_sha,
        recommended_label=recommended_label,
        recommended_current_version=recommended_current_version,
        pull_request_title=pull_request_title,
        pull_request_author_login=pull_request_author_login,
        pull_request_url=pull_request_url,
        release_summary=release_summary,
        source_event_id=source_event_id,
        merged_at=merged_at,
    )
    with self._connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO app_release_backlog (
                repository,
                pull_request_number,
                merge_commit_sha,
                recommended_label,
                recommended_current_version,
                pull_request_title,
                pull_request_author_login,
                pull_request_url,
                release_summary,
                source_event_id,
                merged_at,
                included_in_release_tag,
                included_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL)
            ON CONFLICT(repository, pull_request_number)
            DO UPDATE SET
                merge_commit_sha = EXCLUDED.merge_commit_sha,
                recommended_label = EXCLUDED.recommended_label,
                recommended_current_version = EXCLUDED.recommended_current_version,
                pull_request_title = EXCLUDED.pull_request_title,
                pull_request_author_login = EXCLUDED.pull_request_author_login,
                pull_request_url = EXCLUDED.pull_request_url,
                release_summary = EXCLUDED.release_summary,
                source_event_id = EXCLUDED.source_event_id,
                merged_at = EXCLUDED.merged_at,
                updated_at = NOW()
            RETURNING id
            """,
            (
                normalized.repository,
                normalized.pull_request_number,
                normalized.merge_commit_sha,
                normalized.recommended_label,
                normalized.recommended_current_version,
                normalized.pull_request_title,
                normalized.pull_request_author_login,
                normalized.pull_request_url,
                normalized.release_summary,
                normalized.source_event_id,
                normalized.merged_at,
            ),
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("Postgres did not return id for release backlog upsert.")
    row_map = _postgres_row_mapping(row)
    if row_map["id"] is None:
        raise RuntimeError("Postgres did not return id for release backlog upsert.")
    backlog_id = int(row_map["id"])
    self._record_audit(
        **_build_release_backlog_upserted_payload(
            normalized=normalized,
            backlog_id=backlog_id,
        ).as_kwargs(),
    )
    self._connection.commit()
    return backlog_id


def list_unreleased_release_backlog_items(
    self,
    *,
    repository: str,
    limit: int = 500,
) -> list[ReleaseBacklogItem]:
    normalized_repository = repository.strip()
    if not normalized_repository:
        return []
    with self._connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, repository, pull_request_number, merge_commit_sha,
                   recommended_label, recommended_current_version,
                   pull_request_title, pull_request_author_login, pull_request_url,
                   release_summary, source_event_id,
                   merged_at, included_in_release_tag, included_at
            FROM app_release_backlog
            WHERE repository = %s
              AND included_in_release_tag IS NULL
            ORDER BY merged_at ASC, id ASC
            LIMIT %s
            """,
            (normalized_repository, max(1, int(limit))),
        )
        rows = cursor.fetchall()
    return [_build_release_backlog_item(_postgres_row_mapping(row)) for row in rows]


def mark_release_backlog_items_included(
    self,
    *,
    repository: str,
    backlog_ids: tuple[int, ...],
    release_tag: str,
    included_at: datetime | None = None,
) -> int:
    normalized = _normalize_release_backlog_inclusion_input(
        repository=repository,
        backlog_ids=backlog_ids,
        release_tag=release_tag,
        included_at=included_at,
    )
    if normalized is None:
        return 0
    with self._connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE app_release_backlog
            SET included_in_release_tag = %s,
                included_at = %s,
                updated_at = NOW()
            WHERE repository = %s
              AND id = ANY(%s)
              AND included_in_release_tag IS NULL
            """,
            (
                normalized.release_tag,
                normalized.included_at,
                normalized.repository,
                list(normalized.backlog_ids),
            ),
        )
        updated_count = int(cursor.rowcount or 0)
    if updated_count > 0:
        self._record_audit(
            **_build_release_backlog_included_payload(
                normalized=normalized,
                updated_count=updated_count,
            ).as_kwargs(),
        )
    self._connection.commit()
    return updated_count


class PostgresReleaseBacklogOpsMixin:
    upsert_release_backlog_item = upsert_release_backlog_item
    list_unreleased_release_backlog_items = list_unreleased_release_backlog_items
    mark_release_backlog_items_included = mark_release_backlog_items_included
