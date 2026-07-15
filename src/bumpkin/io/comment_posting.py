from __future__ import annotations

from typing import Any, cast

from bumpkin.io.github_http import github_request_json

COMMENT_MARKER = "<!-- bumpkin:recommendation -->"
BUMPKIN_TITLES = (
    "🤖 Bumpkin Recommendation",
    "🤖 Bumpkin (stub mode)",
    "🤖 Bumpkin (semantic fallback)",
    "🤖 Bumpkin Manual Review Required",
)


def _as_dict(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return cast("dict[str, Any]", value)


def _as_object_list(value: object) -> list[object] | None:
    if not isinstance(value, list):
        return None
    return cast("list[object]", value)


def _is_bumpkin_comment_body(body: str) -> bool:
    normalized = body.strip()
    return COMMENT_MARKER in normalized or normalized.startswith(BUMPKIN_TITLES)


def find_existing_bumpkin_comment_id(comments: list[dict[str, Any]]) -> int | None:
    for comment in reversed(comments):
        if not _is_bumpkin_comment_body(str(comment.get("body", ""))):
            continue
        comment_id = comment.get("id")
        if isinstance(comment_id, int):
            return comment_id
    return None


def _api_request(
    token: str, url: str, method: str, payload: dict[str, Any] | None = None
) -> object:
    response, _headers = github_request_json(
        url=url,
        method=method,
        timeout_seconds=10,
        token=token,
        user_agent="bumpkin",
        payload=payload,
    )
    return response


def post_pr_comment(token: str, repo: str, pr_number: int, body: str) -> None:
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required to post PR comments.")
    if not repo:
        raise RuntimeError("GITHUB_REPOSITORY is required to post PR comments.")

    comments_url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments?per_page=100"
    comments_raw = _api_request(token, comments_url, "GET")
    comments = _as_object_list(comments_raw)
    if comments is None:
        raise RuntimeError("Unexpected comments response shape from GitHub API.")
    typed_comments = [item for item in (_as_dict(entry) for entry in comments) if item is not None]

    existing_id = find_existing_bumpkin_comment_id(typed_comments)
    if existing_id is not None:
        update_url = f"https://api.github.com/repos/{repo}/issues/comments/{existing_id}"
        _api_request(token, update_url, "PATCH", {"body": body})
        return

    create_url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    _api_request(token, create_url, "POST", {"body": body})
