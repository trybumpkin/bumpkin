from __future__ import annotations

from datetime import UTC, datetime

from bumpkin.integrations.github.persistence import ReleaseBacklogItem
from bumpkin.integrations.github.release_aggregation import aggregate_release_backlog


def _item(
    *,
    backlog_id: int,
    pr_number: int,
    label: str,
    version: str | None,
) -> ReleaseBacklogItem:
    return ReleaseBacklogItem(
        id=backlog_id,
        repository="acme/repo",
        pull_request_number=pr_number,
        merge_commit_sha=f"sha-{pr_number}",
        recommended_label=label,
        recommended_current_version=version,
        source_event_id=f"delivery-{pr_number}",
        merged_at=datetime(2026, 3, 21, 12, pr_number % 60, tzinfo=UTC),
        included_in_release_tag=None,
        included_at=None,
    )


def test_aggregate_release_backlog_selects_highest_precedence_label() -> None:
    aggregate = aggregate_release_backlog(
        [
            _item(backlog_id=1, pr_number=70, label="PATCH", version="0.17.0"),
            _item(backlog_id=2, pr_number=71, label="MAJOR", version="0.17.0"),
            _item(backlog_id=3, pr_number=72, label="MINOR", version="0.17.0"),
        ]
    )

    assert aggregate.item_count == 3
    assert aggregate.considered_item_count == 3
    assert aggregate.considered_item_ids == (1, 2, 3)
    assert aggregate.aggregated_label == "MAJOR"
    assert aggregate.recommended_label == "MAJOR"
    assert aggregate.baseline_version == "0.17.0"
    assert aggregate.current_version == "0.17.0"
    assert aggregate.next_version == "0.18.0"
    assert aggregate.target_merge_commit_sha == "sha-72"


def test_aggregate_release_backlog_uses_highest_current_version() -> None:
    aggregate = aggregate_release_backlog(
        [
            _item(backlog_id=1, pr_number=70, label="PATCH", version="0.17.0"),
            _item(backlog_id=2, pr_number=71, label="PATCH", version="0.18.1"),
            _item(backlog_id=3, pr_number=72, label="PATCH", version=None),
        ]
    )

    assert aggregate.item_count == 3
    assert aggregate.considered_item_count == 1
    assert aggregate.considered_item_ids == (2,)
    assert aggregate.aggregated_label == "PATCH"
    assert aggregate.recommended_label == "PATCH"
    assert aggregate.baseline_version == "0.18.1"
    assert aggregate.current_version == "0.18.1"
    assert aggregate.next_version == "0.18.2"
    assert aggregate.target_merge_commit_sha == "sha-71"


def test_aggregate_release_backlog_applies_highest_label_once_per_release() -> None:
    aggregate = aggregate_release_backlog(
        [
            _item(backlog_id=1, pr_number=70, label="MAJOR", version="0.17.0"),
            _item(backlog_id=2, pr_number=71, label="PATCH", version="0.17.0"),
        ]
    )

    assert aggregate.item_count == 2
    assert aggregate.considered_item_count == 2
    assert aggregate.considered_item_ids == (1, 2)
    assert aggregate.aggregated_label == "MAJOR"
    assert aggregate.recommended_label == "MAJOR"
    assert aggregate.baseline_version == "0.17.0"
    assert aggregate.current_version == "0.17.0"
    assert aggregate.next_version == "0.18.0"
    assert aggregate.target_merge_commit_sha == "sha-71"
