from __future__ import annotations

import urllib.error

from bumpkin.io.github_http import (
    format_github_http_error,
    github_request_bytes,
    github_request_json,
)


def bytes_request(*, token: str, url: str, timeout_seconds: int) -> bytes:
    try:
        body, _headers = github_request_bytes(
            url=url,
            method="GET",
            timeout_seconds=timeout_seconds,
            token=token,
            user_agent="bumpkin-release-job",
            strip_auth_on_cross_host_redirects=True,
        )
        return body
    except urllib.error.HTTPError as err:
        raise RuntimeError(format_github_http_error(err, prefix="GitHub API error")) from err
    except urllib.error.URLError as err:
        raise RuntimeError(f"GitHub API request failed: {err.reason}") from err


def json_request(*, token: str, url: str, timeout_seconds: int) -> object:
    try:
        payload, _headers = github_request_json(
            url=url,
            method="GET",
            timeout_seconds=timeout_seconds,
            token=token,
            user_agent="bumpkin-release-job",
        )
        return payload
    except urllib.error.HTTPError as err:
        raise RuntimeError(format_github_http_error(err, prefix="GitHub API error")) from err
    except urllib.error.URLError as err:
        raise RuntimeError(f"GitHub API request failed: {err.reason}") from err
