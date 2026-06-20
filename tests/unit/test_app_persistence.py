from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from bumpkin.integrations.github.guards import ApprovalRecord, PublishGuardDecision
from bumpkin.integrations.github.ingress import AppEventEnvelope
from bumpkin.integrations.github.persistence import SqliteAppStateStore, build_app_state_store
from bumpkin.integrations.github.persistence_record_parsing import (
    build_publish_decision_record,
)
from bumpkin.integrations.github.persistence_write_normalization import (
    normalize_recommendation_snapshot_input,
    normalize_release_backlog_inclusion_input,
    normalize_release_backlog_write_input,
)
from bumpkin.integrations.github.types import AppEvent


def _build_event_and_envelope(
    *, event_id: str, received_at: datetime, comment_body: str = "/bumpkin approve patch"
) -> tuple[AppEvent, AppEventEnvelope]:
    event = AppEvent(
        event="issue_comment",
        action="created",
        installation_id=123,
        repository="acme/repo",
        pull_request_number=7,
        sender_login="octocat",
        delivery_id=event_id,
    )
    envelope = AppEventEnvelope(
        event_id=event_id,
        source="github",
        event_type="issue_comment",
        action="created",
        received_at=received_at,
        headers_hash="headers-hash",
        payload_hash="payload-hash",
        payload={"comment": {"body": comment_body}},
    )
    return event, envelope


def test_sqlite_store_records_event_once_and_ignores_duplicates(tmp_path) -> None:
    store = SqliteAppStateStore(tmp_path / "app.sqlite3")
    now = datetime(2026, 3, 20, 12, 0, tzinfo=UTC)
    event, envelope = _build_event_and_envelope(event_id="delivery-1", received_at=now)

    first = store.record_event(envelope=envelope, event=event)
    second = store.record_event(envelope=envelope, event=event)

    assert first is True
    assert second is False

    stored = store.get_event(provider="github", provider_event_id="delivery-1")
    assert stored is not None
    assert stored.event_type == "issue_comment"
    assert stored.repository == "acme/repo"
    assert stored.pull_request_number == 7
    assert stored.payload["comment"]["body"] == "/bumpkin approve patch"
    store.close()


def test_sqlite_store_tracks_deferred_merge_events_and_status_updates(tmp_path) -> None:
    store = SqliteAppStateStore(tmp_path / "app.sqlite3")
    now = datetime(2026, 3, 21, 9, 0, tzinfo=UTC)
    merge_event = AppEvent(
        event="pull_request",
        action="closed",
        installation_id=123,
        repository="acme/repo",
        pull_request_number=70,
        sender_login="octocat",
        delivery_id="delivery-merge-deferred-1",
        merged=True,
        merge_commit_sha="abc123",
        base_ref="main",
        base_sha="base-sha",
        head_ref="feature",
        head_sha="head-sha",
    )
    merge_envelope = AppEventEnvelope(
        event_id="delivery-merge-deferred-1",
        source="github",
        event_type="pull_request",
        action="closed",
        received_at=now,
        headers_hash="headers-hash",
        payload_hash="payload-hash",
        payload={
            "action": "closed",
            "repository": {"full_name": "acme/repo"},
            "pull_request": {
                "number": 70,
                "merged": True,
                "merge_commit_sha": "abc123",
                "base": {"ref": "main", "sha": "base-sha"},
                "head": {"ref": "feature", "sha": "head-sha"},
            },
            "sender": {"login": "octocat"},
        },
    )
    store.record_event(envelope=merge_envelope, event=merge_event)

    updated = store.update_event_status(
        provider="github",
        provider_event_id="delivery-merge-deferred-1",
        status="deferred_deploy:oldsha",
    )
    assert updated is True

    deferred = store.list_deferred_merge_events(provider="github", repository="acme/repo")
    assert len(deferred) == 1
    assert deferred[0].provider_event_id == "delivery-merge-deferred-1"
    assert deferred[0].status == "deferred_deploy:oldsha"

    store.record_recommendation_snapshot(
        repository="acme/repo",
        pull_request_number=70,
        label="PATCH",
        current_version="1.2.3",
        source="app_merge",
        source_event_id="delivery-merge-deferred-1",
    )
    deferred_after_snapshot = store.list_deferred_merge_events(
        provider="github",
        repository="acme/repo",
    )
    assert deferred_after_snapshot == []
    store.close()


def test_build_app_state_store_prefers_database_url(monkeypatch) -> None:
    sentinel = object()
    calls: list[str] = []

    def fake_postgres_store(database_url: str) -> object:
        calls.append(database_url)
        return sentinel

    monkeypatch.setattr(
        "bumpkin.integrations.github.persistence_factory.PostgresAppStateStore",
        fake_postgres_store,
    )

    store = build_app_state_store(
        db_path="var/bumpkin.sqlite3",
        database_url="postgresql://user:pass@db.example.com:5432/postgres",
    )

    assert store is sentinel
    assert calls == ["postgresql://user:pass@db.example.com:5432/postgres"]


def test_sqlite_store_restores_latest_approval_after_reopen(tmp_path) -> None:
    db_path = tmp_path / "app.sqlite3"
    now = datetime(2026, 3, 20, 12, 0, tzinfo=UTC)
    first_approval = ApprovalRecord(
        repository="acme/repo",
        pull_request_number=7,
        approved_label="PATCH",
        recommendation_hash="hash-a",
        approved_by="maintainer-a",
        approved_at=now - timedelta(hours=2),
    )
    second_approval = ApprovalRecord(
        repository="acme/repo",
        pull_request_number=7,
        approved_label="MINOR",
        recommendation_hash="hash-b",
        approved_by="maintainer-b",
        approved_at=now - timedelta(minutes=15),
    )

    store = SqliteAppStateStore(db_path)
    store.record_approval(approval=first_approval, commit_sha="abc111")
    store.record_approval(approval=second_approval, commit_sha="abc222")
    store.close()

    reopened = SqliteAppStateStore(db_path)
    latest = reopened.latest_approval_for_pr(repository="acme/repo", pull_request_number=7)
    assert latest is not None
    assert latest.approved_label == "MINOR"
    assert latest.recommendation_hash == "hash-b"
    assert latest.approved_by == "maintainer-b"
    reopened.close()


def test_sqlite_store_records_publish_decision_and_audit(tmp_path) -> None:
    store = SqliteAppStateStore(tmp_path / "app.sqlite3")
    decision_id = store.record_publish_decision(
        repository="acme/repo",
        pull_request_number=7,
        commit_sha="abc123",
        decision=PublishGuardDecision(
            allowed=False,
            guard_reasons=("stale_approval", "required_checks_not_green"),
        ),
        policy_snapshot={
            "required_checks": ["test", "lint"],
            "allowed_branches": ["main"],
        },
        evaluated_at=datetime(2026, 3, 20, 12, 30, tzinfo=UTC),
    )

    latest = store.latest_publish_decision_for_pr(repository="acme/repo", pull_request_number=7)
    assert latest is not None
    assert latest.allowed is False
    assert latest.reason == "stale_approval"
    assert latest.guard_reasons == ("stale_approval", "required_checks_not_green")
    assert latest.policy_snapshot["required_checks"] == ["test", "lint"]

    audit_entries = store.list_audit_entries(
        entity_type="publish_decision",
        entity_id=str(decision_id),
    )
    assert audit_entries
    assert audit_entries[0].action == "recorded"
    assert audit_entries[0].details["repository"] == "acme/repo"
    store.close()


def test_sqlite_store_returns_latest_recommended_label_for_pr(tmp_path) -> None:
    store = SqliteAppStateStore(tmp_path / "app.sqlite3")
    now = datetime(2026, 3, 20, 12, 0, tzinfo=UTC)
    first_event, first_envelope = _build_event_and_envelope(
        event_id="delivery-reco-1",
        received_at=now - timedelta(minutes=2),
        comment_body=(
            "<!-- bumpkin:recommendation -->\n"
            "Proposed bump (court): PATCH (high confidence)\n"
            "Next version   : v1.2.2 → v1.2.3\n"
        ),
    )
    second_event, second_envelope = _build_event_and_envelope(
        event_id="delivery-reco-2",
        received_at=now - timedelta(minutes=1),
        comment_body=(
            "<!-- bumpkin:recommendation -->\n"
            "Proposed bump (court): MINOR (medium confidence)\n"
            "Next version   : v1.2.3 → v1.3.0\n"
        ),
    )
    command_event, command_envelope = _build_event_and_envelope(
        event_id="delivery-command-1",
        received_at=now,
        comment_body="/bumpkin minor v1.2.3",
    )
    store.record_event(envelope=first_envelope, event=first_event)
    store.record_event(envelope=second_envelope, event=second_event)
    store.record_event(envelope=command_envelope, event=command_event)

    label = store.latest_recommended_label_for_pr(repository="acme/repo", pull_request_number=7)
    assert label == "MINOR"
    recommendation = store.latest_recommendation_for_pr(
        repository="acme/repo", pull_request_number=7
    )
    assert recommendation is not None
    assert recommendation.label == "MINOR"
    assert recommendation.current_version == "1.2.3"
    store.close()


def test_sqlite_store_parses_current_recommendation_comment_format(tmp_path) -> None:
    store = SqliteAppStateStore(tmp_path / "app.sqlite3")
    now = datetime(2026, 3, 20, 13, 0, tzinfo=UTC)
    event, envelope = _build_event_and_envelope(
        event_id="delivery-reco-current-format-1",
        received_at=now,
        comment_body=(
            "<!-- bumpkin:recommendation -->\n"
            "🤖 Bumpkin Recommendation\n\n"
            "Recommendation : 🟡 MINOR\n"
            "Next version   : 0.17.0 -> v0.18.0\n"
        ),
    )
    store.record_event(envelope=envelope, event=event)

    recommendation = store.latest_recommendation_for_pr(
        repository="acme/repo",
        pull_request_number=7,
    )
    assert recommendation is not None
    assert recommendation.label == "MINOR"
    assert recommendation.current_version == "0.17.0"
    store.close()


def test_sqlite_store_upserts_and_lists_unreleased_release_backlog_items(tmp_path) -> None:
    store = SqliteAppStateStore(tmp_path / "app.sqlite3")
    first_id = store.upsert_release_backlog_item(
        repository="acme/repo",
        pull_request_number=73,
        merge_commit_sha="abc123",
        recommended_label="PATCH",
        recommended_current_version="0.17.0",
        source_event_id="delivery-1",
        merged_at=datetime(2026, 3, 21, 12, 0, tzinfo=UTC),
    )
    second_id = store.upsert_release_backlog_item(
        repository="acme/repo",
        pull_request_number=74,
        merge_commit_sha="def456",
        recommended_label="MINOR",
        recommended_current_version="0.17.0",
        source_event_id="delivery-2",
        merged_at=datetime(2026, 3, 21, 13, 0, tzinfo=UTC),
    )
    updated_first_id = store.upsert_release_backlog_item(
        repository="acme/repo",
        pull_request_number=73,
        merge_commit_sha="abc999",
        recommended_label="MAJOR",
        recommended_current_version="0.17.0",
        source_event_id="delivery-3",
        merged_at=datetime(2026, 3, 21, 14, 0, tzinfo=UTC),
    )

    assert first_id == updated_first_id
    assert second_id != first_id
    items = store.list_unreleased_release_backlog_items(repository="acme/repo")
    assert [item.pull_request_number for item in items] == [74, 73]
    assert items[1].merge_commit_sha == "abc999"
    assert items[1].recommended_label == "MAJOR"
    assert items[1].recommended_current_version == "0.17.0"
    store.close()


def test_sqlite_store_marks_release_backlog_items_as_included(tmp_path) -> None:
    store = SqliteAppStateStore(tmp_path / "app.sqlite3")
    first_id = store.upsert_release_backlog_item(
        repository="acme/repo",
        pull_request_number=73,
        merge_commit_sha="abc123",
        recommended_label="PATCH",
        recommended_current_version="0.17.0",
        source_event_id="delivery-1",
        merged_at=datetime(2026, 3, 21, 12, 0, tzinfo=UTC),
    )
    second_id = store.upsert_release_backlog_item(
        repository="acme/repo",
        pull_request_number=74,
        merge_commit_sha="def456",
        recommended_label="MINOR",
        recommended_current_version="0.17.0",
        source_event_id="delivery-2",
        merged_at=datetime(2026, 3, 21, 13, 0, tzinfo=UTC),
    )

    updated_count = store.mark_release_backlog_items_included(
        repository="acme/repo",
        backlog_ids=(first_id,),
        release_tag="v0.18.0",
        included_at=datetime(2026, 3, 21, 14, 0, tzinfo=UTC),
    )

    assert updated_count == 1
    remaining = store.list_unreleased_release_backlog_items(repository="acme/repo")
    assert [item.id for item in remaining] == [second_id]
    audit_rows = store.list_audit_entries(
        entity_type="release_backlog",
        entity_id="acme/repo:v0.18.0",
    )
    assert audit_rows
    assert audit_rows[-1].details["backlog_ids"] == [first_id]
    assert audit_rows[-1].details["updated_count"] == 1
    store.close()


def test_sqlite_store_prefers_recorded_recommendation_snapshot_for_pr(tmp_path) -> None:
    store = SqliteAppStateStore(tmp_path / "app.sqlite3")
    now = datetime(2026, 3, 20, 12, 0, tzinfo=UTC)
    first_event, first_envelope = _build_event_and_envelope(
        event_id="delivery-reco-fallback-1",
        received_at=now - timedelta(minutes=2),
        comment_body=(
            "<!-- bumpkin:recommendation -->\n"
            "Proposed bump (court): PATCH (high confidence)\n"
            "Next version   : v1.2.2 → v1.2.3\n"
        ),
    )
    store.record_event(envelope=first_envelope, event=first_event)
    store.record_recommendation_snapshot(
        repository="acme/repo",
        pull_request_number=7,
        label="MINOR",
        current_version="1.2.3",
        source="app_merge",
        source_event_id="delivery-merge-1",
    )

    recommendation = store.latest_recommendation_for_pr(
        repository="acme/repo",
        pull_request_number=7,
    )
    assert recommendation is not None
    assert recommendation.label == "MINOR"
    assert recommendation.current_version == "1.2.3"
    store.close()


def test_build_publish_decision_record_parses_guard_reasons_payload() -> None:
    record = build_publish_decision_record(
        {
            "repository": "acme/repo",
            "pull_request_number": 7,
            "commit_sha": "abc123",
            "allowed": 0,
            "reason": "stale_approval",
            "guard_reasons": json.dumps(
                {"guard_reasons": ["stale_approval", "", 3, "required_checks_not_green"]}
            ),
            "evaluated_at": "2026-03-20T12:30:00+00:00",
            "policy_snapshot": json.dumps({"required_checks": ["test", "lint"]}),
        }
    )

    assert record.allowed is False
    assert record.reason == "stale_approval"
    assert record.guard_reasons == ("stale_approval", "required_checks_not_green")
    assert record.policy_snapshot["required_checks"] == ["test", "lint"]


def test_normalize_recommendation_snapshot_input_trims_and_defaults() -> None:
    normalized = normalize_recommendation_snapshot_input(
        repository="  acme/repo  ",
        pull_request_number=7,
        label="minor",
        current_version=" v1.2.3 ",
        source=" ",
        source_event_id=" delivery-1 ",
        recorded_at=datetime(2026, 3, 20, 12, 0, tzinfo=UTC),
    )

    assert normalized.repository == "acme/repo"
    assert normalized.label == "MINOR"
    assert normalized.current_version == "1.2.3"
    assert normalized.source == "unknown"
    assert normalized.source_event_id == "delivery-1"
    assert normalized.recorded_at == "2026-03-20T12:00:00+00:00"


def test_normalize_release_backlog_write_input_cleans_optional_fields() -> None:
    normalized = normalize_release_backlog_write_input(
        repository=" acme/repo ",
        pull_request_number=9,
        merge_commit_sha=" abc123 ",
        recommended_label="patch",
        recommended_current_version=" v0.17.0 ",
        pull_request_title="  Ship it  ",
        pull_request_author_login="  octocat  ",
        pull_request_url=" https://example.com/pr/9 ",
        release_summary="  Summary text.  ",
        source_event_id=" delivery-9 ",
        merged_at=datetime(2026, 3, 21, 12, 0, tzinfo=UTC),
    )

    assert normalized.repository == "acme/repo"
    assert normalized.merge_commit_sha == "abc123"
    assert normalized.recommended_label == "PATCH"
    assert normalized.recommended_current_version == "0.17.0"
    assert normalized.pull_request_title == "Ship it"
    assert normalized.pull_request_author_login == "octocat"
    assert normalized.pull_request_url == "https://example.com/pr/9"
    assert normalized.release_summary == "Summary text."
    assert normalized.source_event_id == "delivery-9"
    assert normalized.merged_at == "2026-03-21T12:00:00+00:00"


def test_normalize_release_backlog_inclusion_input_filters_ids() -> None:
    normalized = normalize_release_backlog_inclusion_input(
        repository=" acme/repo ",
        backlog_ids=(3, -1, 2, 3, 0),
        release_tag=" v1.0.0 ",
        included_at=datetime(2026, 3, 21, 14, 0, tzinfo=UTC),
    )

    assert normalized is not None
    assert normalized.repository == "acme/repo"
    assert normalized.release_tag == "v1.0.0"
    assert normalized.backlog_ids == (2, 3)
    assert normalized.included_at == "2026-03-21T14:00:00+00:00"
