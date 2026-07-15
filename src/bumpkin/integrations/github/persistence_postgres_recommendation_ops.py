from __future__ import annotations

import json
from datetime import datetime

from bumpkin.integrations.github.persistence_audit_payloads import (
    build_recommendation_recorded_payload as _build_recommendation_recorded_payload,
)
from bumpkin.integrations.github.persistence_models import RecommendationSnapshot
from bumpkin.integrations.github.persistence_record_parsing import (
    build_recommendation_snapshot_from_row as _build_recommendation_snapshot_from_row,
)
from bumpkin.integrations.github.persistence_record_parsing import (
    extract_recommendation_snapshot_from_payload as _extract_recommendation_snapshot_from_payload,
)
from bumpkin.integrations.github.persistence_serialization import (
    postgres_row_mapping as _postgres_row_mapping,
)
from bumpkin.integrations.github.persistence_write_normalization import (
    normalize_recommendation_snapshot_input as _normalize_recommendation_snapshot_input,
)


def latest_recommended_label_for_pr(
    self,
    *,
    repository: str,
    pull_request_number: int,
) -> str | None:
    snapshot = self.latest_recommendation_for_pr(
        repository=repository,
        pull_request_number=pull_request_number,
    )
    return snapshot.label if snapshot is not None else None


def latest_recommendation_for_pr(
    self,
    *,
    repository: str,
    pull_request_number: int,
) -> RecommendationSnapshot | None:
    with self._connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT label, current_version
            FROM app_recommendations
            WHERE repository = %s
              AND pull_request_number = %s
            ORDER BY recorded_at DESC, id DESC
            LIMIT 1
            """,
            (repository, pull_request_number),
        )
        snapshot_row = cursor.fetchone()
    if snapshot_row is not None:
        return _build_recommendation_snapshot_from_row(_postgres_row_mapping(snapshot_row))

    with self._connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT payload
            FROM app_events
            WHERE repository = %s
              AND pull_request_number = %s
              AND event_type = 'issue_comment'
            ORDER BY received_at DESC, id DESC
            LIMIT 250
            """,
            (repository, pull_request_number),
        )
        rows = cursor.fetchall()
    for row in rows:
        row_map = _postgres_row_mapping(row)
        payload = json.loads(str(row_map["payload"]))
        snapshot = _extract_recommendation_snapshot_from_payload(payload)
        if snapshot is not None:
            return snapshot
    return None


def record_recommendation_snapshot(
    self,
    *,
    repository: str,
    pull_request_number: int,
    label: str,
    current_version: str | None,
    source: str,
    source_event_id: str | None = None,
    recorded_at: datetime | None = None,
) -> None:
    normalized = _normalize_recommendation_snapshot_input(
        repository=repository,
        pull_request_number=pull_request_number,
        label=label,
        current_version=current_version,
        source=source,
        source_event_id=source_event_id,
        recorded_at=recorded_at,
    )
    with self._connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO app_recommendations (
                repository,
                pull_request_number,
                label,
                current_version,
                source,
                source_event_id,
                recorded_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(repository, pull_request_number)
            DO UPDATE SET
                label = EXCLUDED.label,
                current_version = EXCLUDED.current_version,
                source = EXCLUDED.source,
                source_event_id = EXCLUDED.source_event_id,
                recorded_at = EXCLUDED.recorded_at
            """,
            (
                normalized.repository,
                normalized.pull_request_number,
                normalized.label,
                normalized.current_version,
                normalized.source,
                normalized.source_event_id,
                normalized.recorded_at,
            ),
        )
    self._record_audit(**_build_recommendation_recorded_payload(normalized).as_kwargs())
    self._connection.commit()


class PostgresRecommendationOpsMixin:
    latest_recommended_label_for_pr = latest_recommended_label_for_pr
    latest_recommendation_for_pr = latest_recommendation_for_pr
    record_recommendation_snapshot = record_recommendation_snapshot
