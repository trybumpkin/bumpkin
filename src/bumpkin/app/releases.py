from __future__ import annotations

import urllib.error
from dataclasses import dataclass
from typing import Any, Protocol, cast

from bumpkin.app.github_http import format_github_http_error, github_request_json


@dataclass(frozen=True, slots=True)
class ReleasePublishRequest:
    repository: str
    tag_name: str
    target_sha: str
    body: str
    name: str | None = None
    installation_id: int | None = None


@dataclass(frozen=True, slots=True)
class ReleasePublishResult:
    status: str
    tag_name: str
    url: str | None = None
    message: str | None = None
    release_id: int | None = None


class ReleasePublisher(Protocol):
    def publish(self, request: ReleasePublishRequest) -> ReleasePublishResult: ...


class NoopReleasePublisher:
    def publish(self, request: ReleasePublishRequest) -> ReleasePublishResult:
        return ReleasePublishResult(
            status="skipped",
            tag_name=request.tag_name,
            message="publisher_unavailable",
        )


def _as_dict(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return cast("dict[str, Any]", value)


def _as_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    raise TypeError(f"expected int-like value, got {type(value).__name__}")


class GitHubReleasePublisher:
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

    def publish(self, request: ReleasePublishRequest) -> ReleasePublishResult:
        if not self._token:
            return ReleasePublishResult(
                status="skipped",
                tag_name=request.tag_name,
                message="missing_token",
            )

        repository = request.repository.strip()
        tag_name = request.tag_name.strip()
        target_sha = request.target_sha.strip()
        body = request.body.strip()
        name = request.name.strip() if request.name else tag_name
        if not repository:
            raise ValueError("repository is required.")
        if not tag_name:
            raise ValueError("tag_name is required.")
        if not target_sha:
            raise ValueError("target_sha is required.")
        if not body:
            raise ValueError("body is required.")

        existing_release = self._get_release_by_tag(repository=repository, tag_name=tag_name)
        payload = {
            "tag_name": tag_name,
            "target_commitish": target_sha,
            "name": name,
            "body": body,
            "draft": False,
            "prerelease": False,
            "generate_release_notes": False,
        }
        if existing_release is not None:
            release_id = _as_int(existing_release.get("id"))
            if release_id is None:
                raise RuntimeError("GitHub release payload is missing an id.")
            response = self._api_request(
                url=f"https://api.github.com/repos/{repository}/releases/{release_id}",
                method="PATCH",
                payload=payload,
            )
            response_obj = _as_dict(response)
            if response_obj is None:
                raise RuntimeError("GitHub release update returned an unexpected payload.")
            return ReleasePublishResult(
                status="updated",
                tag_name=tag_name,
                url=self._release_url_from_payload(repository=repository, payload=response_obj),
                release_id=_as_int(response_obj.get("id")),
            )

        response = self._api_request(
            url=f"https://api.github.com/repos/{repository}/releases",
            method="POST",
            payload=payload,
        )
        response_obj = _as_dict(response)
        if response_obj is None:
            raise RuntimeError("GitHub release create returned an unexpected payload.")
        return ReleasePublishResult(
            status="created",
            tag_name=tag_name,
            url=self._release_url_from_payload(repository=repository, payload=response_obj),
            release_id=_as_int(response_obj.get("id")),
        )

    def _get_release_by_tag(self, *, repository: str, tag_name: str) -> dict[str, Any] | None:
        try:
            response = self._api_request(
                url=f"https://api.github.com/repos/{repository}/releases/tags/{tag_name}",
                method="GET",
            )
        except urllib.error.HTTPError as err:
            if err.code == 404:
                return None
            raise RuntimeError(
                format_github_http_error(err, prefix="GitHub release API error")
            ) from err
        return _as_dict(response)

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

    def _release_url_from_payload(self, *, repository: str, payload: dict[str, Any]) -> str | None:
        html_url = payload.get("html_url")
        if html_url is not None:
            return str(html_url).strip() or None
        tag_name = str(payload.get("tag_name", "")).strip()
        if not tag_name:
            return None
        return f"https://github.com/{repository}/releases/tag/{tag_name}"


__all__ = [
    "GitHubReleasePublisher",
    "NoopReleasePublisher",
    "ReleasePublishRequest",
    "ReleasePublishResult",
    "ReleasePublisher",
]
