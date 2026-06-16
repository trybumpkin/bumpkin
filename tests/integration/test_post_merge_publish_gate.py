from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bumpkin.integrations.github.approval_store import InMemoryApprovalStore
from bumpkin.integrations.github.guards import ApprovalRecord, evaluate_publish_for_pr
from bumpkin.integrations.github.persistence import SqliteApprovalStore, SqliteAppStateStore


def test_post_merge_publish_gate_allows_when_approval_matches() -> None:
    now = datetime(2026, 3, 19, 12, 0, tzinfo=UTC)
    store = InMemoryApprovalStore()
    store.put(
        ApprovalRecord(
            repository="acme/repo",
            pull_request_number=12,
            approved_label="MINOR",
            recommendation_hash="hash-a",
            approved_by="maintainer",
            approved_at=now - timedelta(hours=1),
        )
    )

    result = evaluate_publish_for_pr(
        approval_store=store,
        repository="acme/repo",
        pull_request_number=12,
        current_recommendation_hash="hash-a",
        required_checks_passed=True,
        target_branch="main",
        actor_is_release_manager=True,
        now=now,
    )
    assert result.allowed is True
    assert result.guard_reasons == ()


def test_post_merge_publish_gate_blocks_when_approval_missing() -> None:
    now = datetime(2026, 3, 19, 12, 0, tzinfo=UTC)
    store = InMemoryApprovalStore()

    result = evaluate_publish_for_pr(
        approval_store=store,
        repository="acme/repo",
        pull_request_number=99,
        current_recommendation_hash="hash-a",
        required_checks_passed=True,
        target_branch="main",
        actor_is_release_manager=True,
        now=now,
    )
    assert result.allowed is False
    assert "missing_approval" in result.guard_reasons


def test_post_merge_publish_gate_blocks_when_recommendation_changes() -> None:
    now = datetime(2026, 3, 19, 12, 0, tzinfo=UTC)
    store = InMemoryApprovalStore()
    store.put(
        ApprovalRecord(
            repository="acme/repo",
            pull_request_number=12,
            approved_label="MINOR",
            recommendation_hash="hash-a",
            approved_by="maintainer",
            approved_at=now - timedelta(hours=1),
        )
    )

    result = evaluate_publish_for_pr(
        approval_store=store,
        repository="acme/repo",
        pull_request_number=12,
        current_recommendation_hash="hash-b",
        required_checks_passed=True,
        target_branch="main",
        actor_is_release_manager=True,
        now=now,
    )
    assert result.allowed is False
    assert "recommendation_hash_mismatch" in result.guard_reasons


def test_post_merge_publish_gate_uses_sqlite_approval_store(tmp_path) -> None:
    now = datetime(2026, 3, 19, 12, 0, tzinfo=UTC)
    state_store = SqliteAppStateStore(tmp_path / "app.sqlite3")
    approval_store = SqliteApprovalStore(state_store)
    approval_store.put(
        ApprovalRecord(
            repository="acme/repo",
            pull_request_number=12,
            approved_label="MINOR",
            recommendation_hash="hash-a",
            approved_by="maintainer",
            approved_at=now - timedelta(hours=1),
        ),
        commit_sha="abc123",
        source_event_id="delivery-1",
    )

    result = evaluate_publish_for_pr(
        approval_store=approval_store,
        repository="acme/repo",
        pull_request_number=12,
        current_recommendation_hash="hash-a",
        required_checks_passed=True,
        target_branch="main",
        actor_is_release_manager=True,
        now=now,
    )
    assert result.allowed is True
    assert result.guard_reasons == ()
    state_store.close()
