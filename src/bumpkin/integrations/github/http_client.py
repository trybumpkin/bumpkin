from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from bumpkin.io.github_http import (
    collect_paginated_github_json_list,
    github_request_bytes,
    github_request_json,
)


class GitHubHttpClient(Protocol):
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
    ) -> tuple[bytes, Mapping[str, str]]: ...

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
    ) -> tuple[object, Mapping[str, str]]: ...

    def collect_paginated_json_list(
        self,
        *,
        url: str,
        token: str,
        user_agent: str,
        timeout_seconds: int,
    ) -> list[object]: ...


class UrllibGitHubHttpClient:
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
        return github_request_bytes(
            url=url,
            method=method,
            timeout_seconds=timeout_seconds,
            token=token,
            bearer_token=bearer_token,
            user_agent=user_agent,
            payload=payload,
            extra_headers=extra_headers,
        )

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
        return github_request_json(
            url=url,
            method=method,
            timeout_seconds=timeout_seconds,
            token=token,
            bearer_token=bearer_token,
            user_agent=user_agent,
            payload=payload,
            extra_headers=extra_headers,
        )

    def collect_paginated_json_list(
        self,
        *,
        url: str,
        token: str,
        user_agent: str,
        timeout_seconds: int,
    ) -> list[object]:
        return collect_paginated_github_json_list(
            url=url,
            token=token,
            user_agent=user_agent,
            timeout_seconds=timeout_seconds,
        )


DEFAULT_GITHUB_HTTP_CLIENT = UrllibGitHubHttpClient()


__all__ = [
    "DEFAULT_GITHUB_HTTP_CLIENT",
    "GitHubHttpClient",
    "UrllibGitHubHttpClient",
]
