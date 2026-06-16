from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SlashCommand:
    name: str
    args: tuple[str, ...] = ()
    raw: str = ""


@dataclass(frozen=True, slots=True)
class AppEvent:
    event: str
    action: str | None
    installation_id: int | None
    repository: str | None
    pull_request_number: int | None
    sender_login: str | None
    comment_id: int | None = None
    comment_html_url: str | None = None
    delivery_id: str | None = None
    merged: bool | None = None
    merge_commit_sha: str | None = None
    base_ref: str | None = None
    base_sha: str | None = None
    head_ref: str | None = None
    head_sha: str | None = None
