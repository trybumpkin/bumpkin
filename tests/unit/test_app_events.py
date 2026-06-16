from bumpkin.integrations.github.events import (
    is_recommendation_merge_event,
    normalize_webhook_event,
)


def test_normalize_issue_comment_event_uses_issue_number() -> None:
    payload = {
        "action": "created",
        "installation": {"id": 123},
        "repository": {"full_name": "acme/repo"},
        "issue": {"number": 7, "pull_request": {"url": "https://api.github.com/pr/7"}},
        "sender": {"login": "octocat"},
    }

    event = normalize_webhook_event("issue_comment", payload, delivery_id="d-1")
    assert event is not None
    assert event.event == "issue_comment"
    assert event.action == "created"
    assert event.installation_id == 123
    assert event.repository == "acme/repo"
    assert event.pull_request_number == 7
    assert event.sender_login == "octocat"
    assert event.delivery_id == "d-1"


def test_normalize_pull_request_event_uses_pr_number() -> None:
    payload = {
        "action": "closed",
        "installation": {"id": "42"},
        "repository": {"full_name": "acme/repo"},
        "pull_request": {
            "number": 11,
            "merged": True,
            "merge_commit_sha": "abc123",
            "base": {"ref": "main", "sha": "base-sha"},
            "head": {"ref": "feature", "sha": "head-sha"},
        },
        "sender": {"login": "maintainer"},
    }

    event = normalize_webhook_event("pull_request", payload)
    assert event is not None
    assert event.event == "pull_request"
    assert event.pull_request_number == 11
    assert event.installation_id == 42
    assert event.merged is True
    assert event.merge_commit_sha == "abc123"
    assert event.base_ref == "main"
    assert event.base_sha == "base-sha"
    assert event.head_ref == "feature"
    assert event.head_sha == "head-sha"
    assert is_recommendation_merge_event(event) is True


def test_normalize_push_event_without_pr_number() -> None:
    payload = {
        "installation": {"id": 1},
        "repository": {"full_name": "acme/repo"},
        "sender": {"login": "ci-bot"},
    }

    event = normalize_webhook_event("push", payload)
    assert event is not None
    assert event.event == "push"
    assert event.pull_request_number is None
    assert event.merged is None
    assert is_recommendation_merge_event(event) is False


def test_recommendation_merge_event_requires_merged_closed_pull_request() -> None:
    payload = {
        "action": "closed",
        "repository": {"full_name": "acme/repo"},
        "pull_request": {"number": 3, "merged": False},
    }

    event = normalize_webhook_event("pull_request", payload)
    assert event is not None
    assert event.merged is False
    assert is_recommendation_merge_event(event) is False


def test_normalize_unsupported_event_returns_none() -> None:
    payload = {"repository": {"full_name": "acme/repo"}}
    assert normalize_webhook_event("fork", payload) is None
