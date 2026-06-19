from __future__ import annotations

import urllib.error
import urllib.parse
from typing import Protocol, cast

from bumpkin.io.github_http import (
    format_github_http_error,
    github_request_bytes,
    github_request_json,
)
from bumpkin.release.candidate import _parse_iso8601
from bumpkin.release.models import ReleaseScopedPullRequest


def _bytes_request(
    *,
    token: str,
    url: str,
    timeout_seconds: int,
) -> bytes:
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


def _json_request(
    *,
    token: str,
    url: str,
    timeout_seconds: int,
) -> object:
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


class GitHubRepositoryClientProtocol(Protocol):
    def list_tags(self) -> list[str]: ...

    def compare_commits(self, *, base_ref: str, head_ref: str) -> list[str]: ...

    def list_pull_requests_for_commit(self, commit_sha: str) -> list[int]: ...

    def get_pull_request(self, number: int) -> ReleaseScopedPullRequest: ...


class GitHubRepositoryClient:
    def __init__(
        self,
        *,
        repository: str,
        token: str,
        timeout_seconds: int,
    ) -> None:
        normalized_repository = repository.strip()
        if not normalized_repository:
            raise ValueError("repository is required.")
        normalized_token = token.strip()
        if not normalized_token:
            raise ValueError("github token is required.")
        self._repository = normalized_repository
        self._token = normalized_token
        self._timeout_seconds = timeout_seconds

    def list_tags(self) -> list[str]:
        page = 1
        tags: list[str] = []
        while True:
            url = f"https://api.github.com/repos/{self._repository}/tags?per_page=100&page={page}"
            payload = _json_request(
                token=self._token,
                url=url,
                timeout_seconds=self._timeout_seconds,
            )
            if not isinstance(payload, list):
                break
            page_tags: list[str] = []
            for item in cast("list[object]", payload):
                if not isinstance(item, dict):
                    continue
                name = str(cast("dict[str, object]", item).get("name", "")).strip()
                if name:
                    page_tags.append(name)
            tags.extend(page_tags)
            if len(page_tags) < 100:
                break
            page += 1
        return tags

    def compare_commits(self, *, base_ref: str, head_ref: str) -> list[str]:
        encoded_base = urllib.parse.quote(base_ref, safe="")
        encoded_head = urllib.parse.quote(head_ref, safe="")
        url = (
            f"https://api.github.com/repos/{self._repository}/compare/"
            f"{encoded_base}...{encoded_head}"
        )
        payload = _json_request(
            token=self._token,
            url=url,
            timeout_seconds=self._timeout_seconds,
        )
        if not isinstance(payload, dict):
            return []
        commits = cast("dict[str, object]", payload).get("commits", [])
        if not isinstance(commits, list):
            return []
        commit_shas: list[str] = []
        for item in commits:
            if not isinstance(item, dict):
                continue
            sha = str(cast("dict[str, object]", item).get("sha", "")).strip()
            if sha:
                commit_shas.append(sha)
        return list(dict.fromkeys(commit_shas))

    def list_pull_requests_for_commit(self, commit_sha: str) -> list[int]:
        normalized_sha = commit_sha.strip()
        if not normalized_sha:
            return []
        url = f"https://api.github.com/repos/{self._repository}/commits/{normalized_sha}/pulls"
        payload = _json_request(
            token=self._token,
            url=url,
            timeout_seconds=self._timeout_seconds,
        )
        if not isinstance(payload, list):
            return []
        pull_numbers: list[int] = []
        for item in cast("list[object]", payload):
            if not isinstance(item, dict):
                continue
            number = cast("dict[str, object]", item).get("number")
            if isinstance(number, int) and number > 0:
                pull_numbers.append(number)
        return list(dict.fromkeys(pull_numbers))

    def get_pull_request(self, number: int) -> ReleaseScopedPullRequest:
        url = f"https://api.github.com/repos/{self._repository}/pulls/{number}"
        payload = _json_request(
            token=self._token,
            url=url,
            timeout_seconds=self._timeout_seconds,
        )
        if not isinstance(payload, dict):
            raise RuntimeError(
                f"GitHub pull request API returned an unexpected payload for PR #{number}."
            )
        payload_map = cast("dict[str, object]", payload)
        title = str(payload_map.get("title", "")).strip()
        html_url = str(payload_map.get("html_url", "")).strip()
        merge_commit_sha = str(payload_map.get("merge_commit_sha", "")).strip()
        merged_at_raw = str(payload_map.get("merged_at", "")).strip()
        if not merge_commit_sha or not merged_at_raw:
            raise RuntimeError(
                f"PR #{number} is missing merged metadata required for a release batch."
            )
        user = payload_map.get("user")
        author_login = None
        if isinstance(user, dict):
            author_login = str(cast("dict[str, object]", user).get("login", "")).strip() or None
        base = payload_map.get("base")
        head = payload_map.get("head")
        base_ref = base_sha = head_ref = head_sha = None
        if isinstance(base, dict):
            base_map = cast("dict[str, object]", base)
            base_ref = str(base_map.get("ref", "")).strip() or None
            base_sha = str(base_map.get("sha", "")).strip() or None
        if isinstance(head, dict):
            head_map = cast("dict[str, object]", head)
            head_ref = str(head_map.get("ref", "")).strip() or None
            head_sha = str(head_map.get("sha", "")).strip() or None
        labels_raw = payload_map.get("labels")
        labels: list[str] = []
        if isinstance(labels_raw, list):
            for item in cast("list[object]", labels_raw):
                if not isinstance(item, dict):
                    continue
                label_name = str(cast("dict[str, object]", item).get("name", "")).strip()
                if label_name:
                    labels.append(label_name)
        return ReleaseScopedPullRequest(
            repository=self._repository,
            number=number,
            title=title or f"PR #{number}",
            url=html_url or f"https://github.com/{self._repository}/pull/{number}",
            author_login=author_login,
            merged_at=_parse_iso8601(merged_at_raw),
            merge_commit_sha=merge_commit_sha,
            base_ref=base_ref,
            base_sha=base_sha,
            head_ref=head_ref,
            head_sha=head_sha,
            labels=tuple(labels),
        )


def _build_repository_client(
    *,
    repository: str,
    github_token: str,
    request_timeout: int,
) -> GitHubRepositoryClientProtocol:
    return GitHubRepositoryClient(
        repository=repository.strip(),
        token=github_token.strip(),
        timeout_seconds=request_timeout,
    )


__all__ = [
    "GitHubRepositoryClient",
    "GitHubRepositoryClientProtocol",
    "_build_repository_client",
    "_bytes_request",
    "_json_request",
]
