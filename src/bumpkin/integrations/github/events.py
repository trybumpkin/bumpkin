from __future__ import annotations

from typing import Any, cast

from bumpkin.integrations.github.types import AppEvent

SUPPORTED_WEBHOOK_EVENTS = frozenset(
    {"issue_comment", "pull_request", "pull_request_review", "push", "workflow_run"}
)


def _as_dict(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return cast("dict[str, Any]", value)


def _as_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _as_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _pull_request_refs(
    payload: dict[str, Any],
) -> tuple[str | None, str | None, str | None, str | None]:
    pull_request = _as_dict(payload.get("pull_request"))
    if pull_request is None:
        return None, None, None, None
    base = _as_dict(pull_request.get("base"))
    head = _as_dict(pull_request.get("head"))
    return (
        _as_text(base.get("ref")) if base is not None else None,
        _as_text(base.get("sha")) if base is not None else None,
        _as_text(head.get("ref")) if head is not None else None,
        _as_text(head.get("sha")) if head is not None else None,
    )


def _pull_request_merge_metadata(payload: dict[str, Any]) -> tuple[bool | None, str | None]:
    pull_request = _as_dict(payload.get("pull_request"))
    if pull_request is None:
        return None, None
    return _as_bool(pull_request.get("merged")), _as_text(pull_request.get("merge_commit_sha"))


def _extract_pull_request_number(event: str, payload: dict[str, Any]) -> int | None:
    pull_request = _as_dict(payload.get("pull_request"))
    if pull_request is not None:
        number = _as_int(pull_request.get("number"))
        if number is not None:
            return number

    if event == "issue_comment":
        issue = _as_dict(payload.get("issue"))
        if issue is None or _as_dict(issue.get("pull_request")) is None:
            return None
        return _as_int(issue.get("number"))

    if event == "workflow_run":
        workflow_run = _as_dict(payload.get("workflow_run"))
        if workflow_run is None:
            return None
        pull_requests = workflow_run.get("pull_requests")
        if not isinstance(pull_requests, list) or not pull_requests:
            return None
        first = _as_dict(pull_requests[0])
        if first is None:
            return None
        return _as_int(first.get("number"))

    return _as_int(payload.get("number"))


def _extract_comment_metadata(payload: dict[str, Any]) -> tuple[int | None, str | None]:
    comment = _as_dict(payload.get("comment"))
    if comment is None:
        return None, None
    return _as_int(comment.get("id")), _as_text(comment.get("html_url"))


def normalize_webhook_event(
    event_name: str,
    payload: dict[str, Any],
    *,
    delivery_id: str | None = None,
) -> AppEvent | None:
    event = event_name.strip().lower()
    if event not in SUPPORTED_WEBHOOK_EVENTS:
        return None

    installation = _as_dict(payload.get("installation"))
    repository = _as_dict(payload.get("repository"))
    sender = _as_dict(payload.get("sender"))
    merged, merge_commit_sha = _pull_request_merge_metadata(payload)
    base_ref, base_sha, head_ref, head_sha = _pull_request_refs(payload)
    comment_id, comment_html_url = _extract_comment_metadata(payload)

    return AppEvent(
        event=event,
        action=str(payload.get("action", "")).strip() or None,
        installation_id=_as_int(installation.get("id")) if installation is not None else None,
        repository=str(repository.get("full_name", "")).strip() or None
        if repository is not None
        else None,
        pull_request_number=_extract_pull_request_number(event, payload),
        sender_login=str(sender.get("login", "")).strip() or None if sender is not None else None,
        comment_id=comment_id,
        comment_html_url=comment_html_url,
        delivery_id=delivery_id,
        merged=merged,
        merge_commit_sha=merge_commit_sha,
        base_ref=base_ref,
        base_sha=base_sha,
        head_ref=head_ref,
        head_sha=head_sha,
    )


def is_recommendation_merge_event(event: AppEvent) -> bool:
    return (
        event.event == "pull_request"
        and event.action == "closed"
        and event.merged is True
        and event.repository is not None
        and event.pull_request_number is not None
    )
