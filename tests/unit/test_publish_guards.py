from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bumpkin.integrations.github.guards import ApprovalRecord, evaluate_publish_guard


def test_publish_guard_blocks_stale_approval() -> None:
    now = datetime(2026, 3, 19, 12, 0, tzinfo=UTC)
    approval = ApprovalRecord(
        repository="acme/repo",
        pull_request_number=7,
        approved_label="MINOR",
        recommendation_hash="hash-1",
        approved_by="octocat",
        approved_at=now - timedelta(days=8),
    )

    result = evaluate_publish_guard(
        approval=approval,
        current_recommendation_hash="hash-1",
        required_checks_passed=True,
        target_branch="main",
        allowed_branches=("main",),
        actor_is_release_manager=True,
        now=now,
        max_age_days=7,
    )
    assert result.allowed is False
    assert "stale_approval" in result.guard_reasons


def test_publish_guard_blocks_hash_mismatch() -> None:
    now = datetime(2026, 3, 19, 12, 0, tzinfo=UTC)
    approval = ApprovalRecord(
        repository="acme/repo",
        pull_request_number=7,
        approved_label="PATCH",
        recommendation_hash="hash-1",
        approved_by="octocat",
        approved_at=now - timedelta(days=1),
    )

    result = evaluate_publish_guard(
        approval=approval,
        current_recommendation_hash="hash-2",
        required_checks_passed=True,
        target_branch="main",
        allowed_branches=("main",),
        actor_is_release_manager=True,
        now=now,
    )
    assert result.allowed is False
    assert "recommendation_hash_mismatch" in result.guard_reasons


def test_publish_guard_blocks_missing_checks_or_permissions() -> None:
    now = datetime(2026, 3, 19, 12, 0, tzinfo=UTC)
    approval = ApprovalRecord(
        repository="acme/repo",
        pull_request_number=7,
        approved_label="PATCH",
        recommendation_hash="hash-1",
        approved_by="octocat",
        approved_at=now - timedelta(hours=4),
    )

    result = evaluate_publish_guard(
        approval=approval,
        current_recommendation_hash="hash-1",
        required_checks_passed=False,
        target_branch="main",
        allowed_branches=("main",),
        actor_is_release_manager=False,
        now=now,
    )
    assert result.allowed is False
    assert "required_checks_not_green" in result.guard_reasons
    assert "actor_not_authorized" in result.guard_reasons


def test_publish_guard_blocks_unapproved_branch() -> None:
    now = datetime(2026, 3, 19, 12, 0, tzinfo=UTC)
    approval = ApprovalRecord(
        repository="acme/repo",
        pull_request_number=7,
        approved_label="PATCH",
        recommendation_hash="hash-1",
        approved_by="octocat",
        approved_at=now - timedelta(hours=4),
    )

    result = evaluate_publish_guard(
        approval=approval,
        current_recommendation_hash="hash-1",
        required_checks_passed=True,
        target_branch="release/1.x",
        allowed_branches=("main",),
        actor_is_release_manager=True,
        now=now,
    )
    assert result.allowed is False
    assert "branch_not_allowed:release/1.x" in result.guard_reasons


def test_publish_guard_allows_publish_when_all_checks_pass() -> None:
    now = datetime(2026, 3, 19, 12, 0, tzinfo=UTC)
    approval = ApprovalRecord(
        repository="acme/repo",
        pull_request_number=7,
        approved_label="MAJOR",
        recommendation_hash="hash-1",
        approved_by="octocat",
        approved_at=now - timedelta(hours=2),
    )

    result = evaluate_publish_guard(
        approval=approval,
        current_recommendation_hash="hash-1",
        required_checks_passed=True,
        target_branch="main",
        allowed_branches=("main",),
        actor_is_release_manager=True,
        now=now,
    )
    assert result.allowed is True
    assert result.guard_reasons == ()
