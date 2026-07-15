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
from bumpkin.integrations.github.persistence_sqlite_support import SqliteStoreSupport
from bumpkin.integrations.github.persistence_write_normalization import (
    normalize_release_backlog_inclusion_input as _normalize_release_backlog_inclusion_input,
)
from bumpkin.integrations.github.persistence_write_normalization import (
    normalize_release_backlog_write_input as _normalize_release_backlog_write_input,
)


class SqliteReleaseBacklogOpsMixin(SqliteStoreSupport):
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
        self._connection.execute(
            """
            INSERT INTO app_release_backlog (
                repository, pull_request_number, merge_commit_sha,
                recommended_label, recommended_current_version,
                pull_request_title, pull_request_author_login, pull_request_url,
                release_summary, source_event_id, merged_at,
                included_in_release_tag, included_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
            ON CONFLICT(repository, pull_request_number)
            DO UPDATE SET
                merge_commit_sha = excluded.merge_commit_sha,
                recommended_label = excluded.recommended_label,
                recommended_current_version = excluded.recommended_current_version,
                pull_request_title = excluded.pull_request_title,
                pull_request_author_login = excluded.pull_request_author_login,
                pull_request_url = excluded.pull_request_url,
                release_summary = excluded.release_summary,
                source_event_id = excluded.source_event_id,
                merged_at = excluded.merged_at,
                updated_at = CURRENT_TIMESTAMP
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
        row = self._connection.execute(
            """
            SELECT id FROM app_release_backlog
            WHERE repository = ? AND pull_request_number = ?
            LIMIT 1
            """,
            (normalized.repository, normalized.pull_request_number),
        ).fetchone()
        if row is None:
            raise RuntimeError("Release backlog item upsert succeeded but no row was returned.")
        backlog_id = int(row["id"])
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
        rows = self._connection.execute(
            """
            SELECT id, repository, pull_request_number, merge_commit_sha,
                   recommended_label, recommended_current_version,
                   pull_request_title, pull_request_author_login, pull_request_url,
                   release_summary, source_event_id,
                   merged_at, included_in_release_tag, included_at
            FROM app_release_backlog
            WHERE repository = ? AND included_in_release_tag IS NULL
            ORDER BY merged_at ASC, id ASC
            LIMIT ?
            """,
            (normalized_repository, max(1, int(limit))),
        ).fetchall()
        return [_build_release_backlog_item(dict(row)) for row in rows]

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
        updated_count = 0
        for backlog_id in normalized.backlog_ids:
            cursor = self._connection.execute(
                """
                UPDATE app_release_backlog
                SET included_in_release_tag = ?, included_at = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE repository = ? AND id = ?
                  AND included_in_release_tag IS NULL
                """,
                (
                    normalized.release_tag,
                    normalized.included_at,
                    normalized.repository,
                    backlog_id,
                ),
            )
            updated_count += int(cursor.rowcount or 0)
        if updated_count > 0:
            self._record_audit(
                **_build_release_backlog_included_payload(
                    normalized=normalized,
                    updated_count=updated_count,
                ).as_kwargs(),
            )
        self._connection.commit()
        return updated_count
