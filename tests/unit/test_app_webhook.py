from __future__ import annotations

import hmac
import json
from datetime import UTC, datetime
from hashlib import sha256

from bumpkin.integrations.github.reactions import (
    GitHubIssueCommentPublisher,
    ReactionPublishRequest,
)
from bumpkin.integrations.github.recommendations import (
    GitHubRecommendationCommentPublisher,
    MergeRecommendation,
    MergeRecommendationRequest,
)
from bumpkin.integrations.github.releases import ReleasePublishRequest, ReleasePublishResult
from bumpkin.integrations.github.runtime import load_app_runtime_config
from bumpkin.integrations.github.tags import GitHubTagPublisher, TagPublishRequest, TagPublishResult
from bumpkin.integrations.github.webhook import build_app_webhook_service
from bumpkin.integrations.github.workflows import WorkflowDispatchRequest, WorkflowDispatchResult


class _FakeReactionPublisher:
    def __init__(self) -> None:
        self.calls: list[ReactionPublishRequest] = []

    def publish(self, request: ReactionPublishRequest) -> str:
        self.calls.append(request)
        return "https://github.com/acme/repo/issues/7#issuecomment-123"


class _FailingReactionPublisher:
    def publish(self, request: ReactionPublishRequest) -> str:  # noqa: ARG002
        raise RuntimeError("api unavailable")


class _FakeTagPublisher:
    def __init__(self) -> None:
        self.calls: list[TagPublishRequest] = []

    def publish(self, request: TagPublishRequest) -> TagPublishResult:
        self.calls.append(request)
        return TagPublishResult(
            status="created",
            tag_name=request.tag_name,
            url=f"https://github.com/{request.repository}/releases/tag/{request.tag_name}",
        )


class _FailingTagPublisher:
    def publish(self, request: TagPublishRequest) -> TagPublishResult:  # noqa: ARG002
        raise RuntimeError("GitHub tag API error 403: Resource not accessible by integration")


class _FakeReleasePublisher:
    def __init__(self) -> None:
        self.calls: list[ReleasePublishRequest] = []

    def publish(self, request: ReleasePublishRequest) -> ReleasePublishResult:
        self.calls.append(request)
        return ReleasePublishResult(
            status="created",
            tag_name=request.tag_name,
            url=f"https://github.com/{request.repository}/releases/tag/{request.tag_name}",
            release_id=9001,
        )


class _FailingReleasePublisher:
    def publish(self, request: ReleasePublishRequest) -> ReleasePublishResult:  # noqa: ARG002
        raise RuntimeError("GitHub release API error 403: Resource not accessible by integration")


class _FakeRecommendationRunner:
    def __init__(self) -> None:
        self.calls: list[MergeRecommendationRequest] = []

    def generate(self, request: MergeRecommendationRequest) -> MergeRecommendation:
        self.calls.append(request)
        return MergeRecommendation(
            body=(
                "<!-- bumpkin:recommendation -->\n"
                "Proposed bump (court): PATCH (high confidence)\n"
                "Next version   : v1.2.3 -> v1.2.4\n"
            ),
            label="PATCH",
            current_version="1.2.3",
        )


class _FailingRecommendationRunner:
    def generate(self, request: MergeRecommendationRequest) -> MergeRecommendation:  # noqa: ARG002
        raise RuntimeError("runner unavailable")


class _FakeRecommendationPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str]] = []

    def publish(self, *, repository: str, issue_number: int, body: str) -> str:
        self.calls.append((repository, issue_number, body))
        return "https://github.com/acme/repo/pull/7#issuecomment-456"


class _FailingRecommendationPublisher:
    def publish(self, *, repository: str, issue_number: int, body: str) -> str:  # noqa: ARG002
        raise RuntimeError("publish unavailable")


class _FakeInstallationTokenProvider:
    def __init__(self, token: str | None = None) -> None:
        self._token = token if token is not None else "app-installation-auth"
        self.calls: list[int | None] = []

    def get_token(self, installation_id: int | None) -> str | None:
        self.calls.append(installation_id)
        return self._token


class _FakeWorkflowDispatcher:
    def __init__(self) -> None:
        self.calls: list[WorkflowDispatchRequest] = []

    def dispatch(self, request: WorkflowDispatchRequest) -> WorkflowDispatchResult:
        self.calls.append(request)
        return WorkflowDispatchResult(
            status="queued",
            repository=request.repository,
            workflow_id=request.workflow_id,
            ref=request.ref,
            operation=request.operation,
            base_tag=request.base_tag,
            url=f"https://github.com/{request.repository}/actions/workflows/bumpkin.yml",
            message=f"Queued `{request.operation}` on `{request.ref}`.",
        )


def _signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, sha256).hexdigest()


def _headers(
    *,
    secret: str,
    body: bytes,
    delivery_id: str,
    event_name: str = "push",
) -> dict[str, str]:
    return {
        "X-GitHub-Event": event_name,
        "X-Hub-Signature-256": _signature(secret, body),
        "X-GitHub-Delivery": delivery_id,
    }


def _config(db_path: str, *, bump_mismatch_policy: str | None = None) -> dict[str, str]:
    env = {
        "BUMPKIN_APP_WEBHOOK_SECRET": "hook-key-1",
        "BUMPKIN_APP_MODE": "legacy",
        "BUMPKIN_APP_DB_PATH": db_path,
    }
    if bump_mismatch_policy is not None:
        env["BUMPKIN_APP_BUMP_MISMATCH_POLICY"] = bump_mismatch_policy
    return env


def test_webhook_service_accepts_and_persists_valid_event(tmp_path) -> None:
    db_path = str(tmp_path / "app.sqlite3")
    config = load_app_runtime_config(_config(db_path))
    service = build_app_webhook_service(config=config)
    payload = {"repository": {"full_name": "acme/repo"}, "sender": {"login": "octocat"}}
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    response = service.handle_github_webhook(
        headers=_headers(secret=config.webhook_secret, body=body, delivery_id="delivery-1"),
        raw_body=body,
    )

    assert response.status_code == 202
    assert response.payload["outcome"] == "accepted"
    assert response.payload["event"]["delivery_id"] == "delivery-1"
    persisted = service._state_store.get_event(provider="github", provider_event_id="delivery-1")
    assert persisted is not None
    assert persisted.repository == "acme/repo"
    service.close()


def test_webhook_service_returns_duplicate_for_replay(tmp_path) -> None:
    db_path = str(tmp_path / "app.sqlite3")
    config = load_app_runtime_config(_config(db_path))
    service = build_app_webhook_service(config=config)
    payload = {"repository": {"full_name": "acme/repo"}}
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    headers = _headers(secret=config.webhook_secret, body=body, delivery_id="delivery-2")

    first = service.handle_github_webhook(headers=headers, raw_body=body)
    second = service.handle_github_webhook(headers=headers, raw_body=body)

    assert first.status_code == 202
    assert second.status_code == 200
    assert second.payload["outcome"] == "duplicate_ignored"
    service.close()


def test_webhook_service_rejects_invalid_signature(tmp_path) -> None:
    db_path = str(tmp_path / "app.sqlite3")
    config = load_app_runtime_config(_config(db_path))
    service = build_app_webhook_service(config=config)
    body = b'{"repository":{"full_name":"acme/repo"}}'

    response = service.handle_github_webhook(
        headers={
            "X-GitHub-Event": "push",
            "X-Hub-Signature-256": "sha256=deadbeef",
            "X-GitHub-Delivery": "delivery-3",
        },
        raw_body=body,
    )

    assert response.status_code == 401
    assert response.payload["outcome"] == "rejected_signature"
    persisted = service._state_store.get_event(provider="github", provider_event_id="delivery-3")
    assert persisted is None
    service.close()


def test_webhook_service_rejects_missing_event_header(tmp_path) -> None:
    db_path = str(tmp_path / "app.sqlite3")
    config = load_app_runtime_config(_config(db_path))
    service = build_app_webhook_service(config=config)

    response = service.handle_github_webhook(
        headers={},
        raw_body=b"{}",
    )

    assert response.status_code == 400
    assert response.payload["reason"] == "missing_event_name"
    service.close()


def test_webhook_service_rejects_invalid_json_payload(tmp_path) -> None:
    db_path = str(tmp_path / "app.sqlite3")
    config = load_app_runtime_config(_config(db_path))
    service = build_app_webhook_service(config=config)

    response = service.handle_github_webhook(
        headers={
            "X-GitHub-Event": "push",
            "X-Hub-Signature-256": "sha256=deadbeef",
        },
        raw_body=b"{not-json",
    )

    assert response.status_code == 400
    assert response.payload["reason"] == "invalid_payload_json"
    service.close()


def test_webhook_service_reacts_to_bump_command_with_suggested_version(tmp_path) -> None:
    db_path = str(tmp_path / "app.sqlite3")
    config = load_app_runtime_config(_config(db_path))
    fake_publisher = _FakeReactionPublisher()
    service = build_app_webhook_service(config=config, reaction_publisher=fake_publisher)
    payload = {
        "action": "created",
        "repository": {"full_name": "acme/repo"},
        "issue": {"number": 7, "pull_request": {"url": "https://api.github.com/pr/7"}},
        "comment": {"body": "/bump patch v1.2.3"},
        "sender": {"login": "octocat"},
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    response = service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=body,
            delivery_id="delivery-bump-1",
            event_name="issue_comment",
        ),
        raw_body=body,
    )

    assert response.status_code == 202
    assert response.payload["outcome"] == "accepted"
    assert response.payload["command"] == {
        "name": "bump",
        "args": ["patch", "v1.2.3"],
    }
    assert response.payload["reaction"]["type"] == "version_bump_suggestion"
    assert response.payload["reaction"]["applied"] is True
    assert response.payload["reaction"]["next_version"] == "1.2.4"
    assert response.payload["reaction_delivery"]["status"] == "posted"
    assert len(fake_publisher.calls) == 1
    assert fake_publisher.calls[0].repository == "acme/repo"
    assert fake_publisher.calls[0].issue_number == 7
    service.close()


def test_webhook_service_requires_version_when_no_recommendation_context_exists(tmp_path) -> None:
    db_path = str(tmp_path / "app.sqlite3")
    config = load_app_runtime_config(_config(db_path))
    service = build_app_webhook_service(config=config)
    payload = {
        "action": "created",
        "repository": {"full_name": "acme/repo"},
        "issue": {"number": 7, "pull_request": {"url": "https://api.github.com/pr/7"}},
        "comment": {"body": "/bump"},
        "sender": {"login": "octocat"},
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    response = service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=body,
            delivery_id="delivery-bump-no-context-1",
            event_name="issue_comment",
        ),
        raw_body=body,
    )

    assert response.status_code == 202
    assert response.payload["outcome"] == "accepted"
    assert response.payload["reaction"]["applied"] is False
    assert "Provide current version" in response.payload["reaction"]["message"]
    service.close()


def test_webhook_service_surfaces_reaction_delivery_failure_without_failing_ingress(
    tmp_path,
) -> None:
    db_path = str(tmp_path / "app.sqlite3")
    config = load_app_runtime_config(_config(db_path))
    service = build_app_webhook_service(
        config=config,
        reaction_publisher=_FailingReactionPublisher(),
    )
    payload = {
        "action": "created",
        "repository": {"full_name": "acme/repo"},
        "issue": {"number": 7, "pull_request": {"url": "https://api.github.com/pr/7"}},
        "comment": {"body": "/bump patch v1.2.3"},
        "sender": {"login": "octocat"},
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    response = service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=body,
            delivery_id="delivery-bump-failure-1",
            event_name="issue_comment",
        ),
        raw_body=body,
    )

    assert response.status_code == 202
    assert response.payload["outcome"] == "accepted"
    assert response.payload["reaction"]["applied"] is True
    assert response.payload["reaction_delivery"]["status"] == "failed"
    assert response.payload["reaction_delivery"]["reason"] == "publisher_error"
    service.close()


def test_webhook_service_uses_recommended_label_and_version_when_bump_has_no_args(tmp_path) -> None:
    db_path = str(tmp_path / "app.sqlite3")
    config = load_app_runtime_config(_config(db_path))
    service = build_app_webhook_service(config=config)
    recommendation_payload = {
        "action": "created",
        "repository": {"full_name": "acme/repo"},
        "issue": {"number": 7, "pull_request": {"url": "https://api.github.com/pr/7"}},
        "comment": {
            "body": (
                "<!-- bumpkin:recommendation -->\n"
                "Proposed bump (court): MINOR (high confidence)\n"
                "Next version   : v1.2.3 → v1.3.0\n"
            )
        },
        "sender": {"login": "bumpkin[bot]"},
    }
    recommendation_body = json.dumps(
        recommendation_payload, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=recommendation_body,
            delivery_id="delivery-recommendation-minor-1",
            event_name="issue_comment",
        ),
        raw_body=recommendation_body,
    )
    command_payload = {
        "action": "created",
        "repository": {"full_name": "acme/repo"},
        "issue": {"number": 7, "pull_request": {"url": "https://api.github.com/pr/7"}},
        "comment": {"body": "/bump"},
        "sender": {"login": "octocat"},
    }
    command_body = json.dumps(command_payload, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )

    response = service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=command_body,
            delivery_id="delivery-bump-implicit-label-1",
            event_name="issue_comment",
        ),
        raw_body=command_body,
    )

    assert response.status_code == 202
    assert response.payload["outcome"] == "accepted"
    assert response.payload["reaction"]["recommended_label"] == "MINOR"
    assert response.payload["reaction"]["label"] == "MINOR"
    assert response.payload["reaction"]["derived_current_version"] == "1.2.3"
    assert response.payload["reaction"]["applied"] is True
    assert response.payload["reaction"]["next_version"] == "1.3.0"
    service.close()


def test_webhook_service_reacts_to_non_bump_command_with_ack(tmp_path) -> None:
    db_path = str(tmp_path / "app.sqlite3")
    config = load_app_runtime_config(_config(db_path))
    service = build_app_webhook_service(config=config)
    payload = {
        "action": "created",
        "repository": {"full_name": "acme/repo"},
        "issue": {"number": 7, "pull_request": {"url": "https://api.github.com/pr/7"}},
        "comment": {"body": "/bumpkin explain"},
        "sender": {"login": "octocat"},
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    response = service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=body,
            delivery_id="delivery-explain-1",
            event_name="issue_comment",
        ),
        raw_body=body,
    )

    assert response.status_code == 202
    assert response.payload["outcome"] == "accepted"
    assert response.payload["command"]["name"] == "explain"
    assert response.payload["reaction"] == {
        "type": "command_received",
        "command": "explain",
    }
    service.close()


def test_shell_mode_bump_dispatches_release_preview_workflow(tmp_path) -> None:
    config = load_app_runtime_config(
        {
            "BUMPKIN_APP_WEBHOOK_SECRET": "hook-key-1",
            "BUMPKIN_APP_MODE": "shell",
            "BUMPKIN_APP_RELEASE_WORKFLOW_FILE": ".github/workflows/bumpkin.yml",
        }
    )
    fake_dispatcher = _FakeWorkflowDispatcher()
    fake_reaction_publisher = _FakeReactionPublisher()
    service = build_app_webhook_service(
        config=config,
        workflow_dispatcher=fake_dispatcher,
        reaction_publisher=fake_reaction_publisher,
    )
    payload = {
        "action": "created",
        "repository": {
            "full_name": "acme/repo",
            "default_branch": "main",
        },
        "issue": {"number": 7, "pull_request": {"url": "https://api.github.com/pr/7"}},
        "comment": {
            "id": 123,
            "html_url": "https://github.com/acme/repo/pull/7#issuecomment-123",
            "body": "/bump",
        },
        "sender": {"login": "octocat"},
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    response = service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=body,
            delivery_id="delivery-shell-preview-1",
            event_name="issue_comment",
        ),
        raw_body=body,
    )

    assert response.status_code == 202
    assert response.payload["workflow_dispatch"]["status"] == "queued"
    assert response.payload["workflow_dispatch"]["operation"] == "release_preview"
    assert response.payload["workflow_dispatch"]["ref"] == "main"
    assert response.payload["reaction"]["type"] == "workflow_dispatch_requested"
    assert response.payload["reaction"]["applied"] is True
    assert len(fake_dispatcher.calls) == 1
    assert fake_dispatcher.calls[0].operation == "release_preview"
    assert fake_dispatcher.calls[0].ref == "main"
    assert len(fake_reaction_publisher.calls) == 1
    assert fake_reaction_publisher.calls[0].reaction["operation"] == "release_preview"
    assert fake_reaction_publisher.calls[0].comment_id == 123
    service.close()


def test_shell_mode_bump_publish_dispatches_release_publish_workflow(tmp_path) -> None:
    config = load_app_runtime_config(
        {
            "BUMPKIN_APP_WEBHOOK_SECRET": "hook-key-1",
            "BUMPKIN_APP_MODE": "shell",
            "BUMPKIN_APP_RELEASE_WORKFLOW_FILE": ".github/workflows/bumpkin.yml",
            "BUMPKIN_APP_RELEASE_WORKFLOW_REF": "release-main",
        }
    )
    fake_dispatcher = _FakeWorkflowDispatcher()
    service = build_app_webhook_service(
        config=config,
        workflow_dispatcher=fake_dispatcher,
    )
    payload = {
        "action": "created",
        "repository": {"full_name": "acme/repo"},
        "issue": {"number": 9, "pull_request": {"url": "https://api.github.com/pr/9"}},
        "comment": {
            "id": 456,
            "html_url": "https://github.com/acme/repo/pull/9#issuecomment-456",
            "body": "/bump publish v1.2.3",
        },
        "sender": {"login": "octocat"},
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    response = service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=body,
            delivery_id="delivery-shell-publish-1",
            event_name="issue_comment",
        ),
        raw_body=body,
    )

    assert response.status_code == 202
    assert response.payload["workflow_dispatch"]["status"] == "queued"
    assert response.payload["workflow_dispatch"]["operation"] == "release_publish"
    assert response.payload["workflow_dispatch"]["ref"] == "release-main"
    assert response.payload["workflow_dispatch"]["base_tag"] == "v1.2.3"
    assert len(fake_dispatcher.calls) == 1
    assert fake_dispatcher.calls[0].operation == "release_publish"
    assert fake_dispatcher.calls[0].base_tag == "v1.2.3"
    service.close()


def test_webhook_service_generates_and_posts_recommendation_for_merged_pull_request(
    tmp_path,
) -> None:
    db_path = str(tmp_path / "app.sqlite3")
    config = load_app_runtime_config(_config(db_path))
    fake_runner = _FakeRecommendationRunner()
    fake_publisher = _FakeRecommendationPublisher()
    service = build_app_webhook_service(
        config=config,
        recommendation_runner=fake_runner,
        recommendation_publisher=fake_publisher,
    )
    payload = {
        "action": "closed",
        "repository": {"full_name": "acme/repo"},
        "pull_request": {
            "number": 7,
            "merged": True,
            "merge_commit_sha": "abc123",
            "base": {"ref": "main", "sha": "base-sha"},
            "head": {"ref": "feature", "sha": "head-sha"},
        },
        "sender": {"login": "maintainer"},
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    response = service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=body,
            delivery_id="delivery-merge-recommend-1",
            event_name="pull_request",
        ),
        raw_body=body,
    )

    assert response.status_code == 202
    assert response.payload["outcome"] == "accepted"
    assert response.payload["recommendation"]["status"] == "generated"
    assert response.payload["recommendation"]["label"] == "PATCH"
    assert response.payload["recommendation_delivery"]["status"] == "posted"
    assert response.payload["release_backlog"]["status"] == "upserted"
    assert len(fake_runner.calls) == 1
    assert len(fake_publisher.calls) == 1
    assert fake_publisher.calls[0][0] == "acme/repo"
    assert fake_publisher.calls[0][1] == 7
    backlog_items = service._state_store.list_unreleased_release_backlog_items(
        repository="acme/repo"
    )
    assert len(backlog_items) == 1
    assert backlog_items[0].pull_request_number == 7
    assert backlog_items[0].recommended_label == "PATCH"
    service.close()


def test_webhook_service_recommendation_preview_matches_bump_baseline(tmp_path) -> None:
    db_path = str(tmp_path / "app.sqlite3")
    config = load_app_runtime_config(_config(db_path))
    fake_runner = _FakeRecommendationRunner()
    fake_publisher = _FakeRecommendationPublisher()
    service = build_app_webhook_service(
        config=config,
        recommendation_runner=fake_runner,
        recommendation_publisher=fake_publisher,
    )
    service._state_store.upsert_release_backlog_item(
        repository="acme/repo",
        pull_request_number=6,
        merge_commit_sha="seed-sha",
        recommended_label="PATCH",
        recommended_current_version="1.2.4",
        source_event_id="delivery-seed",
    )
    payload = {
        "action": "closed",
        "repository": {"full_name": "acme/repo"},
        "pull_request": {
            "number": 7,
            "merged": True,
            "merge_commit_sha": "abc123",
            "base": {"ref": "main", "sha": "base-sha"},
            "head": {"ref": "feature", "sha": "head-sha"},
        },
        "sender": {"login": "maintainer"},
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    response = service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=body,
            delivery_id="delivery-merge-recommend-preview-1",
            event_name="pull_request",
        ),
        raw_body=body,
    )

    assert response.status_code == 202
    assert response.payload["outcome"] == "accepted"
    assert response.payload["release_preview"]["status"] == "computed"
    assert response.payload["release_preview"]["baseline_version"] == "1.2.4"
    assert response.payload["release_preview"]["highest_unreleased_label"] == "PATCH"
    assert response.payload["release_preview"]["next_version"] == "1.2.5"
    assert len(fake_publisher.calls) == 1
    assert "Next version   : v1.2.4 -> v1.2.5" in fake_publisher.calls[0][2]
    service.close()


def test_webhook_service_defers_self_repo_merge_until_next_deploy(tmp_path) -> None:
    db_path = str(tmp_path / "app.sqlite3")
    env = _config(db_path)
    env["BUMPKIN_APP_SELF_REPOSITORY"] = "acme/repo"
    env["BUMPKIN_APP_DEPLOYMENT_REVISION"] = "deploy-old"
    config = load_app_runtime_config(env)
    fake_runner = _FakeRecommendationRunner()
    fake_publisher = _FakeRecommendationPublisher()
    service = build_app_webhook_service(
        config=config,
        recommendation_runner=fake_runner,
        recommendation_publisher=fake_publisher,
    )
    payload = {
        "action": "closed",
        "repository": {"full_name": "acme/repo"},
        "pull_request": {
            "number": 7,
            "merged": True,
            "merge_commit_sha": "deploy-new",
            "base": {"ref": "main", "sha": "base-sha"},
            "head": {"ref": "feature", "sha": "head-sha"},
        },
        "sender": {"login": "maintainer"},
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    response = service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=body,
            delivery_id="delivery-merge-defer-1",
            event_name="pull_request",
        ),
        raw_body=body,
    )

    assert response.status_code == 202
    assert response.payload["recommendation"]["status"] == "deferred"
    assert response.payload["recommendation_defer"]["status"] == "recorded"
    assert fake_runner.calls == []
    assert fake_publisher.calls == []
    persisted = service._state_store.get_event(
        provider="github", provider_event_id="delivery-merge-defer-1"
    )
    assert persisted is not None
    assert persisted.status == "deferred_deploy:deploy-old"
    service.close()


def test_webhook_service_defers_bump_command_while_waiting_for_new_deploy(tmp_path) -> None:
    db_path = str(tmp_path / "app.sqlite3")
    env = _config(db_path)
    env["BUMPKIN_APP_SELF_REPOSITORY"] = "acme/repo"
    env["BUMPKIN_APP_DEPLOYMENT_REVISION"] = "deploy-old"
    config = load_app_runtime_config(env)
    fake_runner = _FakeRecommendationRunner()
    fake_publisher = _FakeRecommendationPublisher()
    service = build_app_webhook_service(
        config=config,
        recommendation_runner=fake_runner,
        recommendation_publisher=fake_publisher,
    )
    merge_payload = {
        "action": "closed",
        "repository": {"full_name": "acme/repo"},
        "pull_request": {
            "number": 7,
            "merged": True,
            "merge_commit_sha": "deploy-new",
            "base": {"ref": "main", "sha": "base-sha"},
            "head": {"ref": "feature", "sha": "head-sha"},
        },
        "sender": {"login": "maintainer"},
    }
    merge_body = json.dumps(merge_payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=merge_body,
            delivery_id="delivery-merge-defer-cmd-1",
            event_name="pull_request",
        ),
        raw_body=merge_body,
    )

    command_payload = {
        "action": "created",
        "repository": {"full_name": "acme/repo"},
        "issue": {"number": 7, "pull_request": {"url": "https://api.github.com/pr/7"}},
        "comment": {"body": "/bump"},
        "sender": {"login": "octocat"},
    }
    command_body = json.dumps(command_payload, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    response = service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=command_body,
            delivery_id="delivery-bump-defer-cmd-1",
            event_name="issue_comment",
        ),
        raw_body=command_body,
    )

    assert response.status_code == 202
    assert response.payload["outcome"] == "accepted"
    assert response.payload["reaction"]["type"] == "command_deferred"
    assert response.payload["reaction"]["applied"] is False
    assert response.payload["command_defer"]["status"] == "deferred"
    assert response.payload["command_defer"]["deployment_revision"] == "deploy-old"
    assert "reaction_delivery" not in response.payload
    service.close()


def test_webhook_service_replays_deferred_merge_recommendation_on_new_deploy(tmp_path) -> None:
    db_path = str(tmp_path / "app.sqlite3")
    env_old = _config(db_path)
    env_old["BUMPKIN_APP_SELF_REPOSITORY"] = "acme/repo"
    env_old["BUMPKIN_APP_DEPLOYMENT_REVISION"] = "deploy-old"
    old_config = load_app_runtime_config(env_old)
    old_service = build_app_webhook_service(config=old_config)
    payload = {
        "action": "closed",
        "repository": {"full_name": "acme/repo"},
        "pull_request": {
            "number": 7,
            "merged": True,
            "merge_commit_sha": "deploy-new",
            "base": {"ref": "main", "sha": "base-sha"},
            "head": {"ref": "feature", "sha": "head-sha"},
        },
        "sender": {"login": "maintainer"},
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    old_service.handle_github_webhook(
        headers=_headers(
            secret=old_config.webhook_secret,
            body=body,
            delivery_id="delivery-merge-defer-replay-1",
            event_name="pull_request",
        ),
        raw_body=body,
    )
    old_service.close()

    env_new = _config(db_path)
    env_new["BUMPKIN_APP_SELF_REPOSITORY"] = "acme/repo"
    env_new["BUMPKIN_APP_DEPLOYMENT_REVISION"] = "deploy-newer"
    new_config = load_app_runtime_config(env_new)
    replay_runner = _FakeRecommendationRunner()
    replay_publisher = _FakeRecommendationPublisher()
    replay_service = build_app_webhook_service(
        config=new_config,
        recommendation_runner=replay_runner,
        recommendation_publisher=replay_publisher,
    )

    assert len(replay_runner.calls) == 1
    assert len(replay_publisher.calls) == 1
    replay_service.close()


def test_webhook_service_surfaces_recommendation_runner_failure_without_failing_ingress(
    tmp_path,
) -> None:
    db_path = str(tmp_path / "app.sqlite3")
    config = load_app_runtime_config(_config(db_path))
    fake_publisher = _FakeRecommendationPublisher()
    service = build_app_webhook_service(
        config=config,
        recommendation_runner=_FailingRecommendationRunner(),
        recommendation_publisher=fake_publisher,
    )
    payload = {
        "action": "closed",
        "repository": {"full_name": "acme/repo"},
        "pull_request": {"number": 7, "merged": True},
        "sender": {"login": "maintainer"},
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    response = service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=body,
            delivery_id="delivery-merge-recommend-failure-1",
            event_name="pull_request",
        ),
        raw_body=body,
    )

    assert response.status_code == 202
    assert response.payload["outcome"] == "accepted"
    assert response.payload["recommendation"]["status"] == "failed"
    assert response.payload["recommendation"]["reason"] == "runner_error"
    assert "runner unavailable" in response.payload["recommendation"]["message"]
    assert fake_publisher.calls == []
    service.close()


def test_webhook_service_surfaces_recommendation_publish_failure_without_failing_ingress(
    tmp_path,
) -> None:
    db_path = str(tmp_path / "app.sqlite3")
    config = load_app_runtime_config(_config(db_path))
    fake_runner = _FakeRecommendationRunner()
    service = build_app_webhook_service(
        config=config,
        recommendation_runner=fake_runner,
        recommendation_publisher=_FailingRecommendationPublisher(),
    )
    payload = {
        "action": "closed",
        "repository": {"full_name": "acme/repo"},
        "pull_request": {"number": 7, "merged": True},
        "sender": {"login": "maintainer"},
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    response = service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=body,
            delivery_id="delivery-merge-recommend-failure-2",
            event_name="pull_request",
        ),
        raw_body=body,
    )

    assert response.status_code == 202
    assert response.payload["outcome"] == "accepted"
    assert response.payload["recommendation"]["status"] == "generated"
    assert response.payload["recommendation_delivery"]["status"] == "failed"
    assert response.payload["recommendation_delivery"]["reason"] == "publisher_error"
    service.close()


def test_webhook_service_uses_merge_recorded_recommendation_for_followup_bump(tmp_path) -> None:
    db_path = str(tmp_path / "app.sqlite3")
    config = load_app_runtime_config(_config(db_path))
    fake_runner = _FakeRecommendationRunner()
    service = build_app_webhook_service(
        config=config,
        recommendation_runner=fake_runner,
        recommendation_publisher=_FakeRecommendationPublisher(),
    )
    merge_payload = {
        "action": "closed",
        "repository": {"full_name": "acme/repo"},
        "pull_request": {"number": 7, "merged": True},
        "sender": {"login": "maintainer"},
    }
    merge_body = json.dumps(merge_payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=merge_body,
            delivery_id="delivery-merge-recommend-seed-1",
            event_name="pull_request",
        ),
        raw_body=merge_body,
    )

    command_payload = {
        "action": "created",
        "repository": {"full_name": "acme/repo"},
        "issue": {"number": 7, "pull_request": {"url": "https://api.github.com/pr/7"}},
        "comment": {"body": "/bump"},
        "sender": {"login": "octocat"},
    }
    command_body = json.dumps(command_payload, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    response = service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=command_body,
            delivery_id="delivery-bump-after-merge-recommendation-1",
            event_name="issue_comment",
        ),
        raw_body=command_body,
    )

    assert response.status_code == 202
    assert response.payload["outcome"] == "accepted"
    assert response.payload["reaction"]["recommended_label"] == "PATCH"
    assert response.payload["reaction"]["derived_current_version"] == "1.2.3"
    assert response.payload["reaction"]["next_version"] == "1.2.4"
    service.close()


def test_webhook_service_uses_app_installation_token_for_recommendation_runner(tmp_path) -> None:
    db_path = str(tmp_path / "app.sqlite3")
    env = _config(db_path)
    legacy_provider_auth = "legacy-provider-auth"
    env["BUMPKIN_APP_PROVIDER_TOKEN"] = legacy_provider_auth
    env["BUMPKIN_APP_GITHUB_APP_ID"] = "123456"
    env["BUMPKIN_APP_GITHUB_PRIVATE_KEY"] = "-----BEGIN KEY-----\\nabc\\n-----END KEY-----"
    config = load_app_runtime_config(env)
    fake_runner = _FakeRecommendationRunner()
    fake_publisher = _FakeRecommendationPublisher()
    fake_installation_tokens = _FakeInstallationTokenProvider()
    service = build_app_webhook_service(
        config=config,
        recommendation_runner=fake_runner,
        recommendation_publisher=fake_publisher,
        installation_token_provider=fake_installation_tokens,
    )
    payload = {
        "action": "closed",
        "installation": {"id": 99},
        "repository": {"full_name": "acme/repo"},
        "pull_request": {"number": 7, "merged": True},
        "sender": {"login": "maintainer"},
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    response = service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=body,
            delivery_id="delivery-installation-token-runner-1",
            event_name="pull_request",
        ),
        raw_body=body,
    )

    assert response.status_code == 202
    assert response.payload["outcome"] == "accepted"
    assert len(fake_runner.calls) == 1
    assert fake_runner.calls[0].provider_token == fake_installation_tokens._token
    assert fake_installation_tokens.calls == [99]
    service.close()


def test_webhook_service_posts_recommendation_with_app_installation_token(
    tmp_path,
    monkeypatch,
) -> None:
    db_path = str(tmp_path / "app.sqlite3")
    env = _config(db_path)
    env["BUMPKIN_APP_GITHUB_APP_ID"] = "123456"
    env["BUMPKIN_APP_GITHUB_PRIVATE_KEY"] = "-----BEGIN KEY-----\\nabc\\n-----END KEY-----"
    config = load_app_runtime_config(env)
    fake_runner = _FakeRecommendationRunner()
    fake_installation_tokens = _FakeInstallationTokenProvider()
    captured_tokens: list[str] = []

    def _capture_publish(
        self: GitHubRecommendationCommentPublisher,
        *,
        repository: str,
        issue_number: int,
        body: str,
    ) -> str:
        _ = repository, issue_number, body
        captured_tokens.append(self._token)
        return "https://github.com/acme/repo/pull/7#issuecomment-789"

    monkeypatch.setattr(GitHubRecommendationCommentPublisher, "publish", _capture_publish)

    service = build_app_webhook_service(
        config=config,
        recommendation_runner=fake_runner,
        installation_token_provider=fake_installation_tokens,
    )
    payload = {
        "action": "closed",
        "installation": {"id": 99},
        "repository": {"full_name": "acme/repo"},
        "pull_request": {"number": 7, "merged": True},
        "sender": {"login": "maintainer"},
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    response = service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=body,
            delivery_id="delivery-installation-token-publish-1",
            event_name="pull_request",
        ),
        raw_body=body,
    )

    assert response.status_code == 202
    assert response.payload["recommendation_delivery"]["status"] == "posted"
    assert captured_tokens == [fake_installation_tokens._token]
    service.close()


def test_webhook_service_posts_reaction_with_app_installation_token(
    tmp_path,
    monkeypatch,
) -> None:
    db_path = str(tmp_path / "app.sqlite3")
    env = _config(db_path)
    env["BUMPKIN_APP_GITHUB_APP_ID"] = "123456"
    env["BUMPKIN_APP_GITHUB_PRIVATE_KEY"] = "-----BEGIN KEY-----\\nabc\\n-----END KEY-----"
    config = load_app_runtime_config(env)
    fake_installation_tokens = _FakeInstallationTokenProvider()
    captured_tokens: list[str] = []

    def _capture_publish(self: GitHubIssueCommentPublisher, request: ReactionPublishRequest) -> str:
        _ = request
        captured_tokens.append(self._token)
        return "https://github.com/acme/repo/issues/7#issuecomment-123"

    monkeypatch.setattr(GitHubIssueCommentPublisher, "publish", _capture_publish)

    service = build_app_webhook_service(
        config=config,
        installation_token_provider=fake_installation_tokens,
    )
    payload = {
        "action": "created",
        "installation": {"id": 99},
        "repository": {"full_name": "acme/repo"},
        "issue": {"number": 7, "pull_request": {"url": "https://api.github.com/pr/7"}},
        "comment": {"body": "/bump patch v1.2.3"},
        "sender": {"login": "octocat"},
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    response = service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=body,
            delivery_id="delivery-installation-token-reaction-1",
            event_name="issue_comment",
        ),
        raw_body=body,
    )

    assert response.status_code == 202
    assert response.payload["reaction_delivery"]["status"] == "posted"
    assert captured_tokens == [fake_installation_tokens._token]
    service.close()


def test_webhook_service_creates_tag_with_app_installation_token(
    tmp_path,
    monkeypatch,
) -> None:
    db_path = str(tmp_path / "app.sqlite3")
    env = _config(db_path)
    env["BUMPKIN_APP_GITHUB_APP_ID"] = "123456"
    env["BUMPKIN_APP_GITHUB_PRIVATE_KEY"] = "-----BEGIN KEY-----\\nabc\\n-----END KEY-----"
    config = load_app_runtime_config(env)
    fake_installation_tokens = _FakeInstallationTokenProvider()
    captured_tokens: list[str] = []

    def _capture_publish(self: GitHubTagPublisher, request: TagPublishRequest) -> TagPublishResult:
        captured_tokens.append(self._token)
        return TagPublishResult(
            status="created",
            tag_name=request.tag_name,
            url=f"https://github.com/{request.repository}/releases/tag/{request.tag_name}",
        )

    monkeypatch.setattr(GitHubTagPublisher, "publish", _capture_publish)

    fake_reaction_publisher = _FakeReactionPublisher()
    service = build_app_webhook_service(
        config=config,
        installation_token_provider=fake_installation_tokens,
        reaction_publisher=fake_reaction_publisher,
    )
    service._state_store.upsert_release_backlog_item(
        repository="acme/repo",
        pull_request_number=99,
        merge_commit_sha="sha-99",
        recommended_label="PATCH",
        recommended_current_version="1.2.3",
        source_event_id="delivery-99",
    )
    payload = {
        "action": "created",
        "installation": {"id": 99},
        "repository": {"full_name": "acme/repo"},
        "issue": {"number": 99, "pull_request": {"url": "https://api.github.com/pr/99"}},
        "comment": {"body": "/bump"},
        "sender": {"login": "octocat"},
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    response = service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=body,
            delivery_id="delivery-installation-token-tag-1",
            event_name="issue_comment",
        ),
        raw_body=body,
    )

    assert response.status_code == 202
    assert response.payload["tag_delivery"]["status"] == "created"
    assert response.payload["tag_delivery"]["tag_name"] == "v1.2.4"
    assert captured_tokens == [fake_installation_tokens._token]
    assert fake_reaction_publisher.calls
    service.close()


def test_webhook_service_allows_bump_override_with_warning_by_default(tmp_path) -> None:
    db_path = str(tmp_path / "app.sqlite3")
    config = load_app_runtime_config(_config(db_path))
    service = build_app_webhook_service(config=config)
    recommendation_payload = {
        "action": "created",
        "repository": {"full_name": "acme/repo"},
        "issue": {"number": 7, "pull_request": {"url": "https://api.github.com/pr/7"}},
        "comment": {
            "body": (
                "<!-- bumpkin:recommendation -->\n"
                "Proposed bump (court): PATCH (high confidence)\n"
                "Next version   : v1.2.3 → v1.2.4\n"
            )
        },
        "sender": {"login": "bumpkin[bot]"},
    }
    recommendation_body = json.dumps(
        recommendation_payload, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=recommendation_body,
            delivery_id="delivery-recommendation-1",
            event_name="issue_comment",
        ),
        raw_body=recommendation_body,
    )
    command_payload = {
        "action": "created",
        "repository": {"full_name": "acme/repo"},
        "issue": {"number": 7, "pull_request": {"url": "https://api.github.com/pr/7"}},
        "comment": {"body": "/bumpkin minor v1.2.3"},
        "sender": {"login": "octocat"},
    }
    command_body = json.dumps(command_payload, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )

    response = service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=command_body,
            delivery_id="delivery-bump-override-1",
            event_name="issue_comment",
        ),
        raw_body=command_body,
    )

    assert response.status_code == 202
    assert response.payload["outcome"] == "accepted"
    assert response.payload["command"] == {
        "name": "bump",
        "args": ["minor", "v1.2.3"],
    }
    assert response.payload["reaction"]["applied"] is True
    assert response.payload["reaction"]["label"] == "MINOR"
    assert response.payload["reaction"]["recommended_label"] == "PATCH"
    assert response.payload["reaction"]["next_version"] == "1.3.0"
    assert "overrides recommendation PATCH" in response.payload["reaction"]["warning"]
    service.close()


def test_webhook_service_blocks_bump_override_without_force_when_policy_is_block(tmp_path) -> None:
    db_path = str(tmp_path / "app.sqlite3")
    config = load_app_runtime_config(_config(db_path, bump_mismatch_policy="block"))
    service = build_app_webhook_service(config=config)
    recommendation_payload = {
        "action": "created",
        "repository": {"full_name": "acme/repo"},
        "issue": {"number": 7, "pull_request": {"url": "https://api.github.com/pr/7"}},
        "comment": {
            "body": (
                "<!-- bumpkin:recommendation -->\n"
                "Proposed bump (court): PATCH (high confidence)\n"
                "Next version   : v1.2.3 → v1.2.4\n"
            )
        },
        "sender": {"login": "bumpkin[bot]"},
    }
    recommendation_body = json.dumps(
        recommendation_payload, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=recommendation_body,
            delivery_id="delivery-recommendation-2",
            event_name="issue_comment",
        ),
        raw_body=recommendation_body,
    )
    command_payload = {
        "action": "created",
        "repository": {"full_name": "acme/repo"},
        "issue": {"number": 7, "pull_request": {"url": "https://api.github.com/pr/7"}},
        "comment": {"body": "/bumpkin minor v1.2.3"},
        "sender": {"login": "octocat"},
    }
    command_body = json.dumps(command_payload, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )

    response = service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=command_body,
            delivery_id="delivery-bump-override-2",
            event_name="issue_comment",
        ),
        raw_body=command_body,
    )

    assert response.status_code == 202
    assert response.payload["outcome"] == "accepted"
    assert response.payload["reaction"]["applied"] is False
    assert response.payload["reaction"]["policy"] == "block"
    assert "--force" in response.payload["reaction"]["message"]
    service.close()


def test_webhook_service_allows_forced_bump_override_when_policy_is_block(tmp_path) -> None:
    db_path = str(tmp_path / "app.sqlite3")
    config = load_app_runtime_config(_config(db_path, bump_mismatch_policy="block"))
    service = build_app_webhook_service(config=config)
    recommendation_payload = {
        "action": "created",
        "repository": {"full_name": "acme/repo"},
        "issue": {"number": 7, "pull_request": {"url": "https://api.github.com/pr/7"}},
        "comment": {
            "body": (
                "<!-- bumpkin:recommendation -->\n"
                "Proposed bump (court): PATCH (high confidence)\n"
                "Next version   : v1.2.3 → v1.2.4\n"
            )
        },
        "sender": {"login": "bumpkin[bot]"},
    }
    recommendation_body = json.dumps(
        recommendation_payload, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=recommendation_body,
            delivery_id="delivery-recommendation-3",
            event_name="issue_comment",
        ),
        raw_body=recommendation_body,
    )
    command_payload = {
        "action": "created",
        "repository": {"full_name": "acme/repo"},
        "issue": {"number": 7, "pull_request": {"url": "https://api.github.com/pr/7"}},
        "comment": {"body": "/bump force minor"},
        "sender": {"login": "octocat"},
    }
    command_body = json.dumps(command_payload, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )

    response = service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=command_body,
            delivery_id="delivery-bump-override-3",
            event_name="issue_comment",
        ),
        raw_body=command_body,
    )

    assert response.status_code == 202
    assert response.payload["outcome"] == "accepted"
    assert response.payload["reaction"]["applied"] is True
    assert response.payload["reaction"]["policy"] == "block"
    assert response.payload["reaction"]["derived_current_version"] == "1.2.3"
    assert response.payload["reaction"]["next_version"] == "1.3.0"
    assert response.payload["reaction"]["override"]["forced"] is True
    service.close()


def test_webhook_service_bump_aggregates_unreleased_backlog_labels(tmp_path) -> None:
    db_path = str(tmp_path / "app.sqlite3")
    config = load_app_runtime_config(_config(db_path))
    service = build_app_webhook_service(config=config)
    service._state_store.upsert_release_backlog_item(
        repository="acme/repo",
        pull_request_number=70,
        merge_commit_sha="sha-70",
        recommended_label="PATCH",
        recommended_current_version="0.17.0",
        source_event_id="delivery-70",
    )
    service._state_store.upsert_release_backlog_item(
        repository="acme/repo",
        pull_request_number=71,
        merge_commit_sha="sha-71",
        recommended_label="MAJOR",
        recommended_current_version="0.17.0",
        source_event_id="delivery-71",
    )
    command_payload = {
        "action": "created",
        "repository": {"full_name": "acme/repo"},
        "issue": {"number": 71, "pull_request": {"url": "https://api.github.com/pr/71"}},
        "comment": {"body": "/bump"},
        "sender": {"login": "octocat"},
    }
    command_body = json.dumps(command_payload, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )

    response = service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=command_body,
            delivery_id="delivery-bump-backlog-1",
            event_name="issue_comment",
        ),
        raw_body=command_body,
    )

    assert response.status_code == 202
    assert response.payload["outcome"] == "accepted"
    assert response.payload["release_backlog"]["status"] == "loaded"
    assert response.payload["release_backlog"]["items"] == 2
    assert response.payload["release_backlog"]["considered_items"] == 2
    assert response.payload["release_backlog"]["considered_backlog_ids"] == [1, 2]
    assert response.payload["release_backlog"]["aggregated_label"] == "MAJOR"
    assert response.payload["release_backlog"]["recommended_label"] == "MAJOR"
    assert response.payload["release_backlog"]["baseline_version"] == "0.17.0"
    assert response.payload["release_backlog"]["current_version"] == "0.17.0"
    assert response.payload["release_backlog"]["next_version"] == "0.18.0"
    assert response.payload["release_backlog"]["target_merge_commit_sha"] == "sha-71"
    assert response.payload["reaction"]["recommended_label"] == "MAJOR"
    assert response.payload["reaction"]["derived_current_version"] == "0.17.0"
    assert response.payload["reaction"]["next_version"] == "0.18.0"
    service.close()


def test_webhook_service_bump_uses_highest_unreleased_label_once(tmp_path) -> None:
    db_path = str(tmp_path / "app.sqlite3")
    config = load_app_runtime_config(_config(db_path))
    service = build_app_webhook_service(config=config)
    service._state_store.upsert_release_backlog_item(
        repository="acme/repo",
        pull_request_number=80,
        merge_commit_sha="sha-80",
        recommended_label="MAJOR",
        recommended_current_version="0.17.0",
        source_event_id="delivery-80",
    )
    service._state_store.upsert_release_backlog_item(
        repository="acme/repo",
        pull_request_number=81,
        merge_commit_sha="sha-81",
        recommended_label="PATCH",
        recommended_current_version="0.17.0",
        source_event_id="delivery-81",
    )
    command_payload = {
        "action": "created",
        "repository": {"full_name": "acme/repo"},
        "issue": {"number": 81, "pull_request": {"url": "https://api.github.com/pr/81"}},
        "comment": {"body": "/bump"},
        "sender": {"login": "octocat"},
    }
    command_body = json.dumps(command_payload, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )

    response = service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=command_body,
            delivery_id="delivery-bump-backlog-2",
            event_name="issue_comment",
        ),
        raw_body=command_body,
    )

    assert response.status_code == 202
    assert response.payload["outcome"] == "accepted"
    assert response.payload["release_backlog"]["aggregated_label"] == "MAJOR"
    assert response.payload["release_backlog"]["recommended_label"] == "MAJOR"
    assert response.payload["release_backlog"]["target_merge_commit_sha"] == "sha-81"
    assert response.payload["reaction"]["recommended_label"] == "MAJOR"
    assert response.payload["reaction"]["derived_current_version"] == "0.17.0"
    assert response.payload["reaction"]["next_version"] == "0.18.0"
    service.close()


def test_webhook_service_bump_creates_release_tag_and_marks_backlog(tmp_path) -> None:
    db_path = str(tmp_path / "app.sqlite3")
    config = load_app_runtime_config(_config(db_path))
    fake_tag_publisher = _FakeTagPublisher()
    service = build_app_webhook_service(config=config, tag_publisher=fake_tag_publisher)
    backlog_id = service._state_store.upsert_release_backlog_item(
        repository="acme/repo",
        pull_request_number=90,
        merge_commit_sha="sha-90",
        recommended_label="PATCH",
        recommended_current_version="1.2.3",
        source_event_id="delivery-90",
    )
    command_payload = {
        "action": "created",
        "repository": {"full_name": "acme/repo"},
        "issue": {"number": 90, "pull_request": {"url": "https://api.github.com/pr/90"}},
        "comment": {"body": "/bump"},
        "sender": {"login": "octocat"},
    }
    command_body = json.dumps(command_payload, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )

    response = service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=command_body,
            delivery_id="delivery-bump-create-tag-1",
            event_name="issue_comment",
        ),
        raw_body=command_body,
    )

    assert response.status_code == 202
    assert response.payload["outcome"] == "accepted"
    assert response.payload["tag_delivery"]["status"] == "created"
    assert response.payload["tag_delivery"]["tag_name"] == "v1.2.4"
    assert response.payload["tag_delivery"]["target_sha"] == "sha-90"
    assert response.payload["release_backlog_update"]["status"] == "marked_included"
    assert response.payload["release_backlog_update"]["updated_count"] == 1
    assert len(fake_tag_publisher.calls) == 1
    assert fake_tag_publisher.calls[0].tag_name == "v1.2.4"
    assert fake_tag_publisher.calls[0].target_sha == "sha-90"
    remaining = service._state_store.list_unreleased_release_backlog_items(repository="acme/repo")
    assert remaining == []
    rows = service._state_store.list_audit_entries(
        entity_type="release_backlog",
        entity_id="acme/repo:v1.2.4",
    )
    assert rows
    assert rows[-1].details["backlog_ids"] == [backlog_id]
    service.close()


def test_webhook_service_release_cut_publishes_release_notes_and_marks_backlog(tmp_path) -> None:
    db_path = str(tmp_path / "app.sqlite3")
    config = load_app_runtime_config(_config(db_path))
    fake_tag_publisher = _FakeTagPublisher()
    fake_release_publisher = _FakeReleasePublisher()
    fake_reaction_publisher = _FakeReactionPublisher()
    service = build_app_webhook_service(
        config=config,
        tag_publisher=fake_tag_publisher,
        release_publisher=fake_release_publisher,
        reaction_publisher=fake_reaction_publisher,
    )
    service._state_store.upsert_release_backlog_item(
        repository="acme/repo",
        pull_request_number=101,
        merge_commit_sha="sha-101",
        recommended_label="PATCH",
        recommended_current_version="1.2.3",
        pull_request_title="Fix duplicate release inclusion",
        pull_request_author_login="alice",
        pull_request_url="https://github.com/acme/repo/pull/101",
        release_summary="Fix duplicate release inclusion",
        source_event_id="delivery-101",
        merged_at=datetime(2026, 3, 21, 12, 0, tzinfo=UTC),
    )
    service._state_store.upsert_release_backlog_item(
        repository="acme/repo",
        pull_request_number=102,
        merge_commit_sha="sha-102",
        recommended_label="MINOR",
        recommended_current_version="1.2.3",
        pull_request_title="Add release backlog summaries",
        pull_request_author_login="bob",
        pull_request_url="https://github.com/acme/repo/pull/102",
        release_summary="Add release backlog summaries",
        source_event_id="delivery-102",
        merged_at=datetime(2026, 3, 21, 13, 0, tzinfo=UTC),
    )
    command_payload = {
        "action": "created",
        "repository": {"full_name": "acme/repo"},
        "issue": {"number": 102, "pull_request": {"url": "https://api.github.com/pr/102"}},
        "comment": {"body": "/bump publish"},
        "sender": {"login": "octocat"},
    }
    command_body = json.dumps(command_payload, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )

    response = service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=command_body,
            delivery_id="delivery-release-cut-1",
            event_name="issue_comment",
        ),
        raw_body=command_body,
    )

    assert response.status_code == 202
    assert response.payload["outcome"] == "accepted"
    assert response.payload["release_backlog"]["status"] == "loaded"
    assert response.payload["release_backlog"]["items"] == 2
    assert response.payload["release_notes"]["status"] == "rendered"
    assert response.payload["release_notes"]["release_label"] == "MINOR"
    assert response.payload["tag_delivery"]["status"] == "created"
    assert response.payload["tag_delivery"]["tag_name"] == "v1.3.0"
    assert response.payload["release_delivery"]["status"] == "created"
    assert response.payload["release"]["status"] == "published"
    assert response.payload["release"]["tag_name"] == "v1.3.0"
    assert response.payload["reaction"]["type"] == "release_published"
    assert response.payload["reaction"]["applied"] is True
    assert len(fake_tag_publisher.calls) == 1
    assert len(fake_release_publisher.calls) == 1
    assert "PR #101" in fake_release_publisher.calls[0].body
    assert "PR #102" in fake_release_publisher.calls[0].body
    assert "@alice" in fake_release_publisher.calls[0].body
    assert "@bob" in fake_release_publisher.calls[0].body
    assert len(fake_reaction_publisher.calls) == 1
    assert fake_reaction_publisher.calls[0].reaction["type"] == "release_published"
    remaining = service._state_store.list_unreleased_release_backlog_items(repository="acme/repo")
    assert remaining == []
    service.close()


def test_webhook_service_bump_publish_alias_triggers_release_cut(tmp_path) -> None:
    db_path = str(tmp_path / "app.sqlite3")
    config = load_app_runtime_config(_config(db_path))
    fake_tag_publisher = _FakeTagPublisher()
    fake_release_publisher = _FakeReleasePublisher()
    service = build_app_webhook_service(
        config=config,
        tag_publisher=fake_tag_publisher,
        release_publisher=fake_release_publisher,
    )
    service._state_store.upsert_release_backlog_item(
        repository="acme/repo",
        pull_request_number=103,
        merge_commit_sha="sha-103",
        recommended_label="PATCH",
        recommended_current_version="1.2.3",
        pull_request_title="Fix release publish alias",
        pull_request_author_login="carol",
        pull_request_url="https://github.com/acme/repo/pull/103",
        release_summary="Fix release publish alias",
        source_event_id="delivery-103",
        merged_at=datetime(2026, 3, 21, 14, 0, tzinfo=UTC),
    )
    command_payload = {
        "action": "created",
        "repository": {"full_name": "acme/repo"},
        "issue": {"number": 103, "pull_request": {"url": "https://api.github.com/pr/103"}},
        "comment": {"body": "/bump publish"},
        "sender": {"login": "octocat"},
    }
    command_body = json.dumps(command_payload, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )

    response = service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=command_body,
            delivery_id="delivery-release-alias-1",
            event_name="issue_comment",
        ),
        raw_body=command_body,
    )

    assert response.status_code == 202
    assert response.payload["command"]["name"] == "bump"
    assert response.payload["release"]["status"] == "published"
    assert response.payload["tag_delivery"]["tag_name"] == "v1.2.4"
    assert response.payload["release_delivery"]["status"] == "created"
    assert fake_tag_publisher.calls[0].tag_name == "v1.2.4"
    assert fake_release_publisher.calls[0].tag_name == "v1.2.4"
    service.close()


def test_webhook_service_bump_marks_reaction_not_applied_when_tag_publish_fails(tmp_path) -> None:
    db_path = str(tmp_path / "app.sqlite3")
    config = load_app_runtime_config(_config(db_path))
    fake_reaction_publisher = _FakeReactionPublisher()
    service = build_app_webhook_service(
        config=config,
        tag_publisher=_FailingTagPublisher(),
        reaction_publisher=fake_reaction_publisher,
    )
    service._state_store.upsert_release_backlog_item(
        repository="acme/repo",
        pull_request_number=91,
        merge_commit_sha="sha-91",
        recommended_label="PATCH",
        recommended_current_version="1.2.3",
        source_event_id="delivery-91",
    )
    command_payload = {
        "action": "created",
        "repository": {"full_name": "acme/repo"},
        "issue": {"number": 91, "pull_request": {"url": "https://api.github.com/pr/91"}},
        "comment": {"body": "/bump"},
        "sender": {"login": "octocat"},
    }
    command_body = json.dumps(command_payload, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )

    response = service.handle_github_webhook(
        headers=_headers(
            secret=config.webhook_secret,
            body=command_body,
            delivery_id="delivery-bump-failing-tag-1",
            event_name="issue_comment",
        ),
        raw_body=command_body,
    )

    assert response.status_code == 202
    assert response.payload["outcome"] == "accepted"
    assert response.payload["tag_delivery"]["status"] == "failed"
    assert response.payload["reaction"]["applied"] is False
    assert "Not applied: GitHub tag API error 403" in response.payload["reaction"]["message"]
    assert len(fake_reaction_publisher.calls) == 1
    assert fake_reaction_publisher.calls[0].reaction["applied"] is False
    assert (
        "Not applied: GitHub tag API error 403"
        in fake_reaction_publisher.calls[0].reaction["message"]
    )
    service.close()
