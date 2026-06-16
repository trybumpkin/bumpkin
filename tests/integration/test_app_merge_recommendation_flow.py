from __future__ import annotations

import hmac
import json
from hashlib import sha256

from bumpkin.integrations.github.recommendations import (
    MergeRecommendation,
    MergeRecommendationRequest,
)
from bumpkin.integrations.github.runtime import load_app_runtime_config
from bumpkin.integrations.github.webhook import build_app_webhook_service


class _FakeRecommendationRunner:
    def generate(self, request: MergeRecommendationRequest) -> MergeRecommendation:  # noqa: ARG002
        return MergeRecommendation(
            body=(
                "<!-- bumpkin:recommendation -->\n"
                "Proposed bump (court): PATCH (high confidence)\n"
                "Next version   : v2.3.4 -> v2.3.5\n"
            ),
            label="PATCH",
            current_version="2.3.4",
        )


class _FakeRecommendationPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str]] = []

    def publish(self, *, repository: str, issue_number: int, body: str) -> str:
        self.calls.append((repository, issue_number, body))
        return "https://github.com/acme/repo/pull/9#issuecomment-999"


def _signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, sha256).hexdigest()


def _headers(
    *,
    secret: str,
    body: bytes,
    delivery_id: str,
    event_name: str,
) -> dict[str, str]:
    return {
        "X-GitHub-Event": event_name,
        "X-Hub-Signature-256": _signature(secret, body),
        "X-GitHub-Delivery": delivery_id,
    }


def _config(db_path: str) -> dict[str, str]:
    return {
        "BUMPKIN_APP_WEBHOOK_SECRET": "hook-key-1",
        "BUMPKIN_APP_MODE": "legacy",
        "BUMPKIN_APP_DB_PATH": db_path,
    }


def test_merge_event_generates_recommendation_and_followup_bump_uses_it(tmp_path) -> None:
    config = load_app_runtime_config(_config(str(tmp_path / "app.sqlite3")))
    publisher = _FakeRecommendationPublisher()
    service = build_app_webhook_service(
        config=config,
        recommendation_runner=_FakeRecommendationRunner(),
        recommendation_publisher=publisher,
    )
    merge_payload = {
        "action": "closed",
        "repository": {"full_name": "acme/repo"},
        "pull_request": {
            "number": 9,
            "merged": True,
            "title": "Fix duplicate release inclusion",
            "html_url": "https://github.com/acme/repo/pull/9",
            "user": {"login": "alice"},
        },
        "sender": {"login": "maintainer"},
    }
    merge_body = json.dumps(merge_payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    merge_response = service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=merge_body,
            delivery_id="merge-flow-1",
            event_name="pull_request",
        ),
        raw_body=merge_body,
    )

    bump_payload = {
        "action": "created",
        "repository": {"full_name": "acme/repo"},
        "issue": {"number": 9, "pull_request": {"url": "https://api.github.com/pr/9"}},
        "comment": {"body": "/bump"},
        "sender": {"login": "octocat"},
    }
    bump_body = json.dumps(bump_payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    bump_response = service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=bump_body,
            delivery_id="merge-flow-2",
            event_name="issue_comment",
        ),
        raw_body=bump_body,
    )

    assert merge_response.status_code == 202
    assert merge_response.payload["recommendation"]["status"] == "generated"
    assert merge_response.payload["recommendation_delivery"]["status"] == "posted"
    assert merge_response.payload["recommendation_persistence"]["status"] == "stored"
    assert merge_response.payload["release_backlog"]["status"] == "upserted"
    assert publisher.calls and publisher.calls[0][0] == "acme/repo"
    backlog_items = service._state_store.list_unreleased_release_backlog_items(
        repository="acme/repo"
    )
    assert backlog_items
    assert backlog_items[0].pull_request_title == "Fix duplicate release inclusion"
    assert backlog_items[0].pull_request_author_login == "alice"
    assert backlog_items[0].pull_request_url == "https://github.com/acme/repo/pull/9"

    assert bump_response.status_code == 202
    assert bump_response.payload["reaction"]["recommended_label"] == "PATCH"
    assert bump_response.payload["reaction"]["derived_current_version"] == "2.3.4"
    assert bump_response.payload["reaction"]["next_version"] == "2.3.5"
    service.close()


def test_non_merged_pull_request_close_does_not_generate_recommendation(tmp_path) -> None:
    config = load_app_runtime_config(_config(str(tmp_path / "app.sqlite3")))
    publisher = _FakeRecommendationPublisher()
    service = build_app_webhook_service(
        config=config,
        recommendation_runner=_FakeRecommendationRunner(),
        recommendation_publisher=publisher,
    )
    payload = {
        "action": "closed",
        "repository": {"full_name": "acme/repo"},
        "pull_request": {"number": 9, "merged": False},
        "sender": {"login": "maintainer"},
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    response = service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=body,
            delivery_id="merge-flow-non-merged-1",
            event_name="pull_request",
        ),
        raw_body=body,
    )

    assert response.status_code == 202
    assert response.payload["outcome"] == "accepted"
    assert "recommendation" not in response.payload
    assert "recommendation_delivery" not in response.payload
    assert publisher.calls == []
    service.close()
