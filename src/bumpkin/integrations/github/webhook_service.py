from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from bumpkin.integrations.github.events import (
    is_recommendation_merge_event,
    normalize_webhook_event,
)
from bumpkin.integrations.github.persistence import AppStateStore
from bumpkin.integrations.github.recommendations import (
    MergeRecommendationRequest,
    RecommendationPublisher,
    RecommendationRunner,
)
from bumpkin.integrations.github.release_aggregation import aggregate_release_backlog
from bumpkin.integrations.github.types import AppEvent
from bumpkin.integrations.github.webhook_parsing import _extract_pull_request_metadata

_DEFERRED_DEPLOY_STATUS_PREFIX = "deferred_deploy:"

ResolveProviderTokenFn = Callable[[AppEvent | None], str | None]
ResolveRecommendationPublisherFn = Callable[[AppEvent | None], RecommendationPublisher]
ProcessMergeRecommendationFn = Callable[
    [AppEvent, Mapping[str, object], dict[str, Any] | None], None
]


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
    state_store: AppStateStore,
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
        deferred_revision = (
            stored_event.status.removeprefix(_DEFERRED_DEPLOY_STATUS_PREFIX)
            if stored_event.status.startswith(_DEFERRED_DEPLOY_STATUS_PREFIX)
            else None
        )
        if deferred_revision == deployment_revision:
            continue
        event = normalize_webhook_event(
            "pull_request",
            stored_event.payload,
            delivery_id=stored_event.provider_event_id,
        )
        if event is None or not is_recommendation_merge_event(event):
            continue
        if (event.base_ref or "").strip() != "main":
            continue
        process_merge_recommendation_fn(event, stored_event.payload, None)


def has_pending_self_deferred_merge_for_current_deploy(
    *,
    defer_self_merge_recommendation: bool,
    self_repository: str | None,
    deployment_revision: str | None,
    state_store: AppStateStore,
) -> bool:
    if not defer_self_merge_recommendation:
        return False
    if self_repository is None or deployment_revision is None:
        return False
    expected_status = deferred_status_value(deployment_revision)
    try:
        deferred_events = state_store.list_deferred_merge_events(
            provider="github",
            repository=self_repository,
            limit=20,
        )
    except Exception:  # noqa: BLE001 - defer checks must not crash webhook handling
        return False
    return any(event.status == expected_status for event in deferred_events)


def process_merge_recommendation(
    *,
    event: AppEvent,
    payload: Mapping[str, object],
    response_payload: dict[str, Any] | None,
    state_store: AppStateStore,
    recommendation_runner: RecommendationRunner,
    resolve_provider_token: ResolveProviderTokenFn,
    resolve_recommendation_publisher: ResolveRecommendationPublisherFn,
) -> None:
    recommendation_body: str | None = None
    try:
        provider_token = resolve_provider_token(event)
        recommendation_request = MergeRecommendationRequest(
            event=event,
            payload=payload,
            provider_token=provider_token,
        )
        recommendation = recommendation_runner.generate(recommendation_request)
        recommendation_body = recommendation.body
    except Exception as err:  # noqa: BLE001 - recommendation generation failures are surfaced
        if response_payload is not None:
            response_payload["recommendation"] = {
                "status": "failed",
                "reason": "runner_error",
                "message": str(err).strip() or "recommendation generation failed",
            }
        return

    if response_payload is not None:
        response_payload["recommendation"] = {
            "status": "generated",
            "label": recommendation.label,
            "current_version": recommendation.current_version,
        }
    if (
        recommendation.label is not None
        and event.repository is not None
        and event.pull_request_number is not None
    ):
        try:
            state_store.record_recommendation_snapshot(
                repository=event.repository,
                pull_request_number=event.pull_request_number,
                label=recommendation.label,
                current_version=recommendation.current_version,
                source="app_merge",
                source_event_id=event.delivery_id,
            )
        except Exception as err:  # noqa: BLE001 - persistence failures should not fail ingress
            if response_payload is not None:
                response_payload["recommendation_persistence"] = {
                    "status": "failed",
                    "reason": "store_error",
                    "message": str(err).strip() or "recommendation snapshot persistence failed",
                }
        else:
            if response_payload is not None:
                response_payload["recommendation_persistence"] = {"status": "stored"}
        try:
            merge_commit_sha = (
                event.merge_commit_sha or event.head_sha or event.base_sha or ""
            ).strip()
            if not merge_commit_sha:
                merge_commit_sha = f"unknown-pr-{event.pull_request_number}"
            pr_metadata = _extract_pull_request_metadata(payload)
            backlog_id = state_store.upsert_release_backlog_item(
                repository=event.repository,
                pull_request_number=event.pull_request_number,
                merge_commit_sha=merge_commit_sha,
                recommended_label=recommendation.label,
                recommended_current_version=recommendation.current_version,
                pull_request_title=pr_metadata["pull_request_title"],
                pull_request_author_login=pr_metadata["pull_request_author_login"],
                pull_request_url=pr_metadata["pull_request_url"],
                release_summary=pr_metadata["release_summary"],
                source_event_id=event.delivery_id,
            )
        except Exception as err:  # noqa: BLE001 - backlog persistence failures should not fail ingress
            if response_payload is not None:
                response_payload["release_backlog"] = {
                    "status": "failed",
                    "reason": "store_error",
                    "message": str(err).strip() or "release backlog persistence failed",
                }
        else:
            if response_payload is not None:
                response_payload["release_backlog"] = {
                    "status": "upserted",
                    "id": backlog_id,
                }
            try:
                backlog_items = state_store.list_unreleased_release_backlog_items(
                    repository=event.repository,
                )
            except Exception:  # noqa: BLE001 - preview should not fail recommendation handling
                backlog_items = []
            if backlog_items:
                aggregate = aggregate_release_backlog(backlog_items)
                recommendation_body = _rewrite_recommendation_next_version(
                    body=recommendation_body or recommendation.body,
                    current_version=aggregate.current_version,
                    next_version=aggregate.next_version,
                )
                if response_payload is not None:
                    response_payload["release_preview"] = {
                        "status": "computed",
                        "baseline_version": aggregate.current_version,
                        "highest_unreleased_label": aggregate.recommended_label
                        or aggregate.aggregated_label,
                        "next_version": aggregate.next_version,
                    }
    try:
        published_url = resolve_recommendation_publisher(event).publish(
            repository=event.repository or "",
            issue_number=event.pull_request_number or 0,
            body=recommendation_body or recommendation.body,
        )
    except Exception as err:  # noqa: BLE001 - publishing failures should not fail ingress
        if response_payload is not None:
            response_payload["recommendation_delivery"] = {
                "status": "failed",
                "reason": "publisher_error",
                "message": str(err).strip() or "recommendation publish failed",
            }
        return
    if response_payload is not None:
        if published_url:
            response_payload["recommendation_delivery"] = {
                "status": "posted",
                "url": published_url,
            }
        else:
            response_payload["recommendation_delivery"] = {
                "status": "skipped",
                "reason": "publisher_unavailable",
            }


def _rewrite_recommendation_next_version(
    *,
    body: str,
    current_version: str | None,
    next_version: str | None,
) -> str:
    from bumpkin.integrations.github.webhook import _rewrite_recommendation_next_version as rewrite

    return rewrite(
        body=body,
        current_version=current_version,
        next_version=next_version,
    )


__all__ = [
    "build_event_payload",
    "deferred_status_value",
    "has_pending_self_deferred_merge_for_current_deploy",
    "process_merge_recommendation",
    "replay_deferred_merge_recommendations_once",
    "should_defer_merge_recommendation",
]
