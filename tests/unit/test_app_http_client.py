from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone

from bumpkin.integrations.github.github_auth import GitHubAppInstallationTokenProvider
from bumpkin.integrations.github.reactions import (
    GitHubIssueCommentPublisher,
    ReactionPublishRequest,
)
from bumpkin.integrations.github.recommendations import (
    MergeRecommendationRequest,
    PipelineRecommendationRunner,
)
from bumpkin.integrations.github.types import AppEvent
from bumpkin.integrations.github.workflows import GitHubWorkflowDispatcher, WorkflowDispatchRequest
from bumpkin.orchestrator import pipeline as orchestrator_pipeline


class _FakeGitHubHttpClient:
    def __init__(self) -> None:
        self.json_calls: list[dict[str, object]] = []
        self.bytes_calls: list[dict[str, object]] = []
        self.paginated_calls: list[dict[str, object]] = []
        self.next_json_response: tuple[object, dict[str, str]] = ({}, {})
        self.next_bytes_response: tuple[bytes, dict[str, str]] = (b"", {})
        self.next_paginated_response: list[object] = []

    def request_json(
        self,
        *,
        url: str,
        method: str,
        timeout_seconds: int,
        token: str | None = None,
        bearer_token: str | None = None,
        user_agent: str,
        payload: object | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> tuple[object, Mapping[str, str]]:
        self.json_calls.append(
            {
                "url": url,
                "method": method,
                "timeout_seconds": timeout_seconds,
                "token": token,
                "bearer_token": bearer_token,
                "user_agent": user_agent,
                "payload": payload,
                "extra_headers": extra_headers,
            }
        )
        return self.next_json_response

    def request_bytes(
        self,
        *,
        url: str,
        method: str,
        timeout_seconds: int,
        token: str | None = None,
        bearer_token: str | None = None,
        user_agent: str,
        payload: object | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> tuple[bytes, Mapping[str, str]]:
        self.bytes_calls.append(
            {
                "url": url,
                "method": method,
                "timeout_seconds": timeout_seconds,
                "token": token,
                "bearer_token": bearer_token,
                "user_agent": user_agent,
                "payload": payload,
                "extra_headers": extra_headers,
            }
        )
        return self.next_bytes_response

    def collect_paginated_json_list(
        self,
        *,
        url: str,
        token: str,
        user_agent: str,
        timeout_seconds: int,
    ) -> list[object]:
        self.paginated_calls.append(
            {
                "url": url,
                "token": token,
                "user_agent": user_agent,
                "timeout_seconds": timeout_seconds,
            }
        )
        return list(self.next_paginated_response)


class _InjectedClientTokenProvider(GitHubAppInstallationTokenProvider):
    def __init__(self, http_client: _FakeGitHubHttpClient) -> None:
        super().__init__(
            app_id="12345",
            private_key_pem="-----BEGIN KEY-----\nabc\n-----END KEY-----",
            http_client=http_client,
        )

    def _build_app_jwt(self, *, now: datetime) -> str:  # noqa: ARG002
        return "app-jwt-token"


def test_installation_token_provider_uses_injected_http_client() -> None:
    http_client = _FakeGitHubHttpClient()
    http_client.next_json_response = (
        {
            "token": "installation-token-1",
            "expires_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017
        },
        {},
    )
    provider = _InjectedClientTokenProvider(http_client)

    assert provider.get_token(42) == "installation-token-1"
    assert http_client.json_calls == [
        {
            "url": "https://api.github.com/app/installations/42/access_tokens",
            "method": "POST",
            "timeout_seconds": 10,
            "token": None,
            "bearer_token": "app-jwt-token",
            "user_agent": "bumpkin-app",
            "payload": {},
            "extra_headers": {"X-GitHub-Api-Version": "2022-11-28"},
        }
    ]


def test_issue_comment_publisher_uses_injected_http_client() -> None:
    http_client = _FakeGitHubHttpClient()
    http_client.next_json_response = (
        {"html_url": "https://github.com/acme/repo/issues/7#comment"},
        {},
    )
    publisher = GitHubIssueCommentPublisher(token="token-123", http_client=http_client)

    result = publisher.publish(
        ReactionPublishRequest(
            repository="acme/repo",
            issue_number=7,
            command_name="bump",
            command_args=(),
            command_raw="/bump",
            reaction={"type": "version_bump_suggestion", "applied": True, "label": "PATCH"},
        )
    )

    assert result == "https://github.com/acme/repo/issues/7#comment"
    assert (
        http_client.json_calls[0]["url"]
        == "https://api.github.com/repos/acme/repo/issues/7/comments"
    )


def test_workflow_dispatcher_uses_injected_http_client() -> None:
    http_client = _FakeGitHubHttpClient()
    dispatcher = GitHubWorkflowDispatcher(token="token-123", http_client=http_client)

    result = dispatcher.dispatch(
        WorkflowDispatchRequest(
            repository="acme/repo",
            workflow_id=".github/workflows/bumpkin.yml",
            ref="main",
            operation="release_preview",
        )
    )

    assert result.status == "queued"
    assert http_client.bytes_calls == [
        {
            "url": "https://api.github.com/repos/acme/repo/actions/workflows/.github%2Fworkflows%2Fbumpkin.yml/dispatches",
            "method": "POST",
            "timeout_seconds": 10,
            "token": "token-123",
            "bearer_token": None,
            "user_agent": "bumpkin-app",
            "payload": {"ref": "main", "inputs": {"operation": "release_preview"}},
            "extra_headers": None,
        }
    ]


def test_pipeline_runner_uses_injected_http_client_for_pr_file_fallback(monkeypatch) -> None:
    http_client = _FakeGitHubHttpClient()
    http_client.next_paginated_response = [
        {
            "filename": "src/example.py",
            "status": "modified",
            "patch": "@@ -1 +1 @@\n-old\n+new\n",
        }
    ]
    event = AppEvent(
        event="pull_request",
        action="closed",
        installation_id=1,
        delivery_id="delivery-1",
        repository="acme/repo",
        pull_request_number=68,
        sender_login="octocat",
        merged=True,
        merge_commit_sha="merge-sha",
        base_ref="main",
        base_sha="base-sha",
        head_ref="feature",
        head_sha="head-sha",
    )
    payload = {
        "pull_request": {"number": 68, "merged": True},
        "repository": {"full_name": "acme/repo"},
    }
    runner = PipelineRecommendationRunner(
        model="gemini-2.5-flash",
        models_endpoint="https://generativelanguage.googleapis.com/v1beta/openai/",
        http_client=http_client,
    )

    def fake_ensure(_: AppEvent) -> None:
        raise RuntimeError("git unavailable")

    observed: dict[str, object] = {}

    def fake_run(_: object, *, comment_poster=None) -> int:
        diff_result = orchestrator_pipeline.build_diff(
            from_ref="base",
            to_ref="merge",
            ignore_patterns=[],
            allowed_files=None,
            token_cap=6000,
            use_difftastic=False,
            chunking_enabled=True,
        )
        observed["files"] = diff_result.analyzed_files
        assert comment_poster is not None
        comment_poster(
            token="",
            repo="acme/repo",
            pr_number=68,
            body=(
                "<!-- bumpkin:recommendation -->\n"
                "Proposed bump (court): PATCH (low confidence)\n"
                "Next version   : v1.2.3 -> v1.2.4\n"
            ),
        )
        return 0

    monkeypatch.setattr(
        "bumpkin.integrations.github.recommendations._ensure_event_refs_available", fake_ensure
    )
    monkeypatch.setattr(
        "bumpkin.integrations.github.recommendations.orchestrator_pipeline.run", fake_run
    )

    recommendation = runner.generate(
        MergeRecommendationRequest(
            event=event,
            payload=payload,
            provider_token="token-123",
        )
    )

    assert recommendation.label == "PATCH"
    assert observed["files"] == ["src/example.py"]
    assert http_client.paginated_calls == [
        {
            "url": "https://api.github.com/repos/acme/repo/pulls/68/files?per_page=100",
            "token": "token-123",
            "user_agent": "bumpkin-app",
            "timeout_seconds": 10,
        }
    ]
