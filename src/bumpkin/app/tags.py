from __future__ import annotations

import json
import urllib.error
import urllib.parse
from dataclasses import dataclass
from typing import Any, Protocol, cast

from bumpkin.app.github_http import format_github_http_error, github_request_json


@dataclass(frozen=True, slots=True)
class TagPublishRequest:
    repository: str
    tag_name: str
    target_sha: str
    installation_id: int | None = None


@dataclass(frozen=True, slots=True)
class TagPublishResult:
    status: str
    tag_name: str
    url: str | None = None
    message: str | None = None


class TagPublisher(Protocol):
    def publish(self, request: TagPublishRequest) -> TagPublishResult: ...


class NoopTagPublisher:
    def publish(self, request: TagPublishRequest) -> TagPublishResult:
        return TagPublishResult(
            status="skipped",
            tag_name=request.tag_name,
            message="publisher_unavailable",
        )


def _as_dict(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return cast("dict[str, Any]", value)


class GitHubTagPublisher:
    def __init__(
        self,
        *,
        token: str,
        user_agent: str = "bumpkin-app",
        timeout_seconds: int = 10,
    ) -> None:
        self._token = token.strip()
        self._user_agent = user_agent.strip() or "bumpkin-app"
        self._timeout_seconds = timeout_seconds

    def publish(self, request: TagPublishRequest) -> TagPublishResult:
        if not self._token:
            return TagPublishResult(
                status="skipped",
                tag_name=request.tag_name,
                message="missing_token",
            )
        tag_name = request.tag_name.strip()
        target_sha = request.target_sha.strip()
        repository = request.repository.strip()
        if not tag_name:
            raise ValueError("tag_name is required.")
        if not target_sha:
            raise ValueError("target_sha is required.")
        if not repository:
            raise ValueError("repository is required.")

        ref = f"refs/tags/{tag_name}"
        try:
            self._api_request(
                url=f"https://api.github.com/repos/{repository}/git/refs",
                method="POST",
                payload={"ref": ref, "sha": target_sha},
            )
        except urllib.error.HTTPError as err:
            if err.code == 422 and self._is_ref_exists_error(err):
                return TagPublishResult(
                    status="exists",
                    tag_name=tag_name,
                    url=_tag_url(repository=repository, tag_name=tag_name),
                    message="tag_already_exists",
                )
            raise RuntimeError(
                format_github_http_error(err, prefix="GitHub tag API error")
            ) from err

        return TagPublishResult(
            status="created",
            tag_name=tag_name,
            url=_tag_url(repository=repository, tag_name=tag_name),
        )

    def _api_request(
        self,
        *,
        url: str,
        method: str,
        payload: dict[str, Any] | None = None,
    ) -> object:
        response, _headers = github_request_json(
            url=url,
            method=method,
            timeout_seconds=self._timeout_seconds,
            token=self._token,
            user_agent=self._user_agent,
            payload=payload,
        )
        return response

    def _is_ref_exists_error(self, err: urllib.error.HTTPError) -> bool:
        try:
            body = err.read().decode("utf-8")
        except Exception:  # noqa: BLE001 - keep 422 fallback resilient
            return False
        if not body.strip():
            return False
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return "Reference already exists" in body
        payload_obj = _as_dict(payload)
        if payload_obj is None:
            return "Reference already exists" in body
        message = str(payload_obj.get("message", "")).strip()
        return "Reference already exists" in message


def _tag_url(*, repository: str, tag_name: str) -> str:
    return f"https://github.com/{repository}/releases/tag/{urllib.parse.quote(tag_name, safe='')}"


__all__ = [
    "GitHubTagPublisher",
    "NoopTagPublisher",
    "TagPublishRequest",
    "TagPublishResult",
    "TagPublisher",
]
