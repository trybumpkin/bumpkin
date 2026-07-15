from __future__ import annotations

from bumpkin.integrations.github.events import (
    is_recommendation_merge_event,
    normalize_webhook_event,
)
from bumpkin.integrations.github.persistence_protocols import EventPersistenceStore
from bumpkin.integrations.github.types import AppEvent
from bumpkin.integrations.github.webhook_service_types import ProcessMergeRecommendationFn

_DEFERRED_DEPLOY_STATUS_PREFIX = "deferred_deploy:"


def deferred_status_value(deployment_revision: str | None) -> str:
    revision = deployment_revision or "unknown"
    return f"{_DEFERRED_DEPLOY_STATUS_PREFIX}{revision}"


def should_defer_merge_recommendation(
    event: AppEvent,
    *,
    defer_self_merge_recommendation: bool,
    self_repository: str | None,
    deployment_revision: str | None,
) -> bool:
    if not defer_self_merge_recommendation:
        return False
    if self_repository is None or deployment_revision is None:
        return False
    if not is_recommendation_merge_event(event):
        return False
    repository = (event.repository or "").strip().lower()
    if repository != self_repository:
        return False
    if (event.base_ref or "").strip() != "main":
        return False
    merge_commit_sha = (event.merge_commit_sha or "").strip()
    if not merge_commit_sha:
        return False
    return merge_commit_sha != deployment_revision


def replay_deferred_merge_recommendations_once(
    *,
    defer_self_merge_recommendation: bool,
    self_repository: str | None,
    deployment_revision: str | None,
    state_store: EventPersistenceStore,
    process_merge_recommendation_fn: ProcessMergeRecommendationFn,
) -> None:
    if not defer_self_merge_recommendation:
        return
    if self_repository is None or deployment_revision is None:
        return
    try:
        deferred_events = state_store.list_deferred_merge_events(
            provider="github",
            repository=self_repository,
            limit=20,
        )
    except Exception:  # noqa: BLE001 - startup catch-up should not crash service boot
        return

    for stored_event in deferred_events:
        if _deferred_event_matches_current_deploy(stored_event.status, deployment_revision):
            continue
        event = normalize_webhook_event(
            "pull_request",
            stored_event.payload,
            delivery_id=stored_event.provider_event_id,
        )
        if event is not None and _is_replayable_merge_event(event):
            process_merge_recommendation_fn(event, stored_event.payload, None)


def _deferred_event_matches_current_deploy(status: str, deployment_revision: str) -> bool:
    return status.removeprefix(_DEFERRED_DEPLOY_STATUS_PREFIX) == deployment_revision


def _is_replayable_merge_event(event: AppEvent | None) -> bool:
    if event is None:
        return False
    return is_recommendation_merge_event(event) and (event.base_ref or "").strip() == "main"


def has_pending_self_deferred_merge_for_current_deploy(
    *,
    defer_self_merge_recommendation: bool,
    self_repository: str | None,
    deployment_revision: str | None,
    state_store: EventPersistenceStore,
) -> bool:
    if not defer_self_merge_recommendation:
        return False
    if self_repository is None or deployment_revision is None:
        return False
    try:
        deferred_events = state_store.list_deferred_merge_events(
            provider="github",
            repository=self_repository,
            limit=20,
        )
    except Exception:  # noqa: BLE001 - defer checks must not crash webhook handling
        return False
    expected_status = deferred_status_value(deployment_revision)
    return any(event.status == expected_status for event in deferred_events)
