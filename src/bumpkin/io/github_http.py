from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import cast

DEFAULT_GITHUB_ACCEPT = "application/vnd.github+json"


def build_github_headers(
    *,
    token: str | None = None,
    bearer_token: str | None = None,
    user_agent: str,
    accept: str = DEFAULT_GITHUB_ACCEPT,
    include_json_content_type: bool = False,
    extra_headers: Mapping[str, str] | None = None,
) -> dict[str, str]:
    headers: dict[str, str] = {
        "Accept": accept,
        "User-Agent": user_agent,
    }
    auth_token = (bearer_token if bearer_token is not None else token) or ""
    normalized_token = auth_token.strip()
    if normalized_token:
        headers["Authorization"] = f"Bearer {normalized_token}"
    if include_json_content_type:
        headers["Content-Type"] = "application/json"
    if extra_headers:
        headers.update({str(key): str(value) for key, value in extra_headers.items()})
    return headers


def github_request_bytes(
    *,
    url: str,
    method: str,
    timeout_seconds: int,
    token: str | None = None,
    bearer_token: str | None = None,
    user_agent: str,
    payload: object | None = None,
    accept: str = DEFAULT_GITHUB_ACCEPT,
    extra_headers: Mapping[str, str] | None = None,
    strip_auth_on_cross_host_redirects: bool = False,
) -> tuple[bytes, Mapping[str, str]]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = build_github_headers(
        token=token,
        bearer_token=bearer_token,
        user_agent=user_agent,
        accept=accept,
        include_json_content_type=payload is not None,
        extra_headers=extra_headers,
    )
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers=headers,
    )

    opener = urllib.request.build_opener()
    if strip_auth_on_cross_host_redirects:

        class _GitHubRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
                redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
                if redirected is None:
                    return None
                original_host = urllib.parse.urlparse(req.full_url).netloc
                redirected_host = urllib.parse.urlparse(newurl).netloc
                if original_host and redirected_host and original_host != redirected_host:
                    redirected.headers.pop("Authorization", None)
                return redirected

        opener = urllib.request.build_opener(_GitHubRedirectHandler)

    with opener.open(request, timeout=max(1, timeout_seconds)) as response:
        body = response.read()
        response_headers = dict(response.headers.items())
    return body, response_headers


def github_request_json(
    *,
    url: str,
    method: str,
    timeout_seconds: int,
    token: str | None = None,
    bearer_token: str | None = None,
    user_agent: str,
    payload: object | None = None,
    accept: str = DEFAULT_GITHUB_ACCEPT,
    extra_headers: Mapping[str, str] | None = None,
    strip_auth_on_cross_host_redirects: bool = False,
) -> tuple[object, Mapping[str, str]]:
    body, response_headers = github_request_bytes(
        url=url,
        method=method,
        timeout_seconds=timeout_seconds,
        token=token,
        bearer_token=bearer_token,
        user_agent=user_agent,
        payload=payload,
        accept=accept,
        extra_headers=extra_headers,
        strip_auth_on_cross_host_redirects=strip_auth_on_cross_host_redirects,
    )
    text = body.decode("utf-8")
    payload_object: object = json.loads(text) if text else {}
    return payload_object, response_headers


def parse_next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        section = part.strip()
        if 'rel="next"' not in section:
            continue
        match = re.search(r"<([^>]+)>", section)
        if match:
            return match.group(1).strip()
    return None


def format_github_http_error(err: urllib.error.HTTPError, *, prefix: str) -> str:
    try:
        body = err.read().decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - preserve best-effort error details
        body = ""
    detail = body.strip()
    if detail:
        return f"{prefix} {err.code}: {detail}"
    return f"{prefix} {err.code}: {err.reason}"


def collect_paginated_github_json_list(
    *,
    url: str,
    token: str,
    user_agent: str,
    timeout_seconds: int,
) -> list[object]:
    collected: list[object] = []
    next_url: str | None = url
    while next_url:
        payload, response_headers = github_request_json(
            url=next_url,
            method="GET",
            timeout_seconds=timeout_seconds,
            token=token,
            user_agent=user_agent,
        )
        if not isinstance(payload, list):
            raise RuntimeError("unexpected GitHub paginated response shape.")
        collected.extend(cast("list[object]", payload))
        next_url = parse_next_link(str(response_headers.get("Link", "")).strip() or None)
    return collected
