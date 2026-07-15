from __future__ import annotations

from typing import Any

from bumpkin.integrations.github.types import AppEvent


def build_event_payload(event: AppEvent) -> dict[str, Any]:
    return {
        "event": event.event,
        "delivery_id": event.delivery_id,
        "repository": event.repository,
        "pull_request_number": event.pull_request_number,
        "merged": event.merged,
        "merge_commit_sha": event.merge_commit_sha,
        "base_ref": event.base_ref,
        "base_sha": event.base_sha,
        "head_ref": event.head_ref,
        "head_sha": event.head_sha,
    }
