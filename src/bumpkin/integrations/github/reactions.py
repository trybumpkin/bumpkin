from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, cast

from bumpkin.integrations.github.http_client import DEFAULT_GITHUB_HTTP_CLIENT, GitHubHttpClient

REACTION_COMMENT_MARKER = "<!-- bumpkin:app-reaction -->"


@dataclass(frozen=True, slots=True)
class ReactionPublishRequest:
    repository: str
    issue_number: int
    command_name: str
    command_args: tuple[str, ...]
    command_raw: str
    reaction: dict[str, Any]
    comment_id: int | None = None
    comment_html_url: str | None = None
    installation_id: int | None = None


class ReactionPublisher(Protocol):
    def publish(self, request: ReactionPublishRequest) -> str | None: ...


class NoopReactionPublisher:
    def publish(self, request: ReactionPublishRequest) -> str | None:  # noqa: ARG002
        return None


def _as_dict(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return cast("dict[str, Any]", value)


def format_reaction_comment(request: ReactionPublishRequest) -> str:
    reaction = request.reaction
    lines = [
        REACTION_COMMENT_MARKER,
        "Bumpkin app reaction",
        "",
        f"Command: `{request.command_raw or f'/{request.command_name}'}`",
    ]
    if reaction.get("type") != "version_bump_suggestion":
        reaction_type = str(reaction.get("type", "command_received")).strip() or "command_received"
        lines.append(f"Status: `{reaction_type}`")
        if reaction_type in {"release_published", "release_cut"}:
            tag_name = str(reaction.get("tag_name", "")).strip()
            if tag_name:
                lines.append(f"Tag: `{tag_name}`")
            release_url = str(reaction.get("release_url", "")).strip()
            if release_url:
                lines.append(f"Release: {release_url}")
            included_prs = reaction.get("included_prs")
            if isinstance(included_prs, int) and included_prs >= 0:
                lines.append(f"Included PRs: `{included_prs}`")
            message = str(reaction.get("message", "")).strip()
            if message:
                lines.append(f"Message: {message}")
            lines.append(
                f"Result: `{'applied' if bool(reaction.get('applied')) else 'not_applied'}`"
            )
        elif reaction_type == "workflow_dispatch_requested":
            operation = str(reaction.get("operation", "")).strip()
            if operation:
                lines.append(f"Operation: `{operation}`")
            workflow_id = str(reaction.get("workflow_id", "")).strip()
            if workflow_id:
                lines.append(f"Workflow: `{workflow_id}`")
            ref = str(reaction.get("ref", "")).strip()
            if ref:
                lines.append(f"Ref: `{ref}`")
            base_tag = str(reaction.get("base_tag", "")).strip()
            if base_tag:
                lines.append(f"Base tag: `{base_tag}`")
            workflow_url = str(reaction.get("workflow_url", "")).strip()
            if workflow_url:
                lines.append(f"Workflow runs: {workflow_url}")
            message = str(reaction.get("message", "")).strip()
            if message:
                lines.append(f"Message: {message}")
            lines.append(f"Result: `{'queued' if bool(reaction.get('applied')) else 'not_queued'}`")
        return "\n".join(lines).strip() + "\n"

    applied = bool(reaction.get("applied"))
    label = str(reaction.get("label", "")).strip().upper() or "PATCH"
    recommended = str(reaction.get("recommended_label", "")).strip().upper()
    if recommended:
        lines.append(f"Recommended label: `{recommended}`")
    lines.append(f"Applied label: `{label}`")

    current_version = str(reaction.get("current_version", "")).strip()
    if not current_version:
        current_version = str(reaction.get("derived_current_version", "")).strip()
    next_version = str(reaction.get("next_version", "")).strip()
    if current_version and next_version:
        lines.append(f"Version: `v{current_version}` -> `v{next_version}`")

    policy = str(reaction.get("policy", "")).strip()
    if policy:
        lines.append(f"Policy: `{policy}`")

    warning = str(reaction.get("warning", "")).strip()
    if warning:
        lines.append(f"Warning: {warning}")

    message = str(reaction.get("message", "")).strip()
    if message:
        lines.append(f"Message: {message}")

    lines.append(f"Result: `{'applied' if applied else 'not_applied'}`")
    return "\n".join(lines).strip() + "\n"


def reaction_emoji_for_request(request: ReactionPublishRequest) -> str | None:
    reaction = request.reaction
    reaction_type = str(reaction.get("type", "")).strip()
    if reaction_type == "workflow_dispatch_requested":
        operation = str(reaction.get("operation", "")).strip()
        if operation == "release_preview":
            return "eyes"
        if operation == "release_publish":
            return "rocket"
        return "eyes"
    if reaction_type == "release_published":
        return "hooray"
    return None


class _GitHubReactionPublisher:
    def __init__(
        self,
        *,
        token: str,
        user_agent: str = "bumpkin-app",
        timeout_seconds: int = 10,
        http_client: GitHubHttpClient = DEFAULT_GITHUB_HTTP_CLIENT,
    ) -> None:
        self._token = token.strip()
        self._user_agent = user_agent.strip() or "bumpkin-app"
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client

    def _request_json(
        self,
        *,
        url: str,
        method: str,
        payload: dict[str, Any] | None = None,
    ) -> object:
        response, _headers = self._http_client.request_json(
            url=url,
            method=method,
            timeout_seconds=self._timeout_seconds,
            token=self._token,
            user_agent=self._user_agent,
            payload=payload,
        )
        return response


class GitHubIssueCommentPublisher(_GitHubReactionPublisher):
    def publish(self, request: ReactionPublishRequest) -> str | None:
        if not self._token:
            return None
        url = (
            f"https://api.github.com/repos/{request.repository}/issues/"
            f"{request.issue_number}/comments"
        )
        payload = {"body": format_reaction_comment(request)}
        response = self._request_json(url=url, method="POST", payload=payload)
        response_obj = _as_dict(response)
        if response_obj is None:
            return None
        html_url = response_obj.get("html_url")
        return str(html_url).strip() if html_url is not None else None


class GitHubIssueCommentReactionPublisher(_GitHubReactionPublisher):
    def __init__(
        self,
        *,
        token: str,
        user_agent: str = "bumpkin-app",
        timeout_seconds: int = 10,
        http_client: GitHubHttpClient = DEFAULT_GITHUB_HTTP_CLIENT,
    ) -> None:
        super().__init__(
            token=token,
            user_agent=user_agent,
            timeout_seconds=timeout_seconds,
            http_client=http_client,
        )

    def publish(self, request: ReactionPublishRequest) -> str | None:
        if not self._token:
            return None
        if request.comment_id is None:
            return None
        emoji = reaction_emoji_for_request(request)
        if emoji is None:
            return None
        url = (
            f"https://api.github.com/repos/{request.repository}/issues/comments/"
            f"{request.comment_id}/reactions"
        )
        payload = {"content": emoji}
        self._http_client.request_bytes(
            url=url,
            method="POST",
            timeout_seconds=self._timeout_seconds,
            token=self._token,
            user_agent=self._user_agent,
            payload=payload,
        )
        return request.comment_html_url
