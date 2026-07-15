from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from bumpkin.integrations.github.persistence_protocols import RecommendationReleaseBacklogStore
from bumpkin.integrations.github.recommendations import (
    MergeRecommendation,
    MergeRecommendationRequest,
    RecommendationRunner,
)
from bumpkin.integrations.github.release_aggregation import aggregate_release_backlog
from bumpkin.integrations.github.types import AppEvent
from bumpkin.integrations.github.webhook_parsing import (
    _extract_pull_request_metadata,
    _normalize_version_token,
)
from bumpkin.integrations.github.webhook_service_types import (
    ResolveProviderTokenFn,
    ResolveRecommendationPublisherFn,
)

_NEXT_VERSION_LINE_RE = re.compile(r"(?im)^next version\s*:\s*.*$")


def process_merge_recommendation(
    *,
    event: AppEvent,
    payload: Mapping[str, object],
    response_payload: dict[str, Any] | None,
    state_store: RecommendationReleaseBacklogStore,
    recommendation_runner: RecommendationRunner,
    resolve_provider_token: ResolveProviderTokenFn,
    resolve_recommendation_publisher: ResolveRecommendationPublisherFn,
) -> None:
    recommendation = _generate_recommendation(
        event=event,
        payload=payload,
        response_payload=response_payload,
        state_store=state_store,
        recommendation_runner=recommendation_runner,
        resolve_provider_token=resolve_provider_token,
    )
    if recommendation is None:
        return
    recommendation_body = _persist_recommendation_context(
        event=event,
        payload=payload,
        recommendation=recommendation,
        response_payload=response_payload,
        state_store=state_store,
    )
    _publish_recommendation(
        event=event,
        body=recommendation_body,
        original_body=recommendation.body,
        response_payload=response_payload,
        resolve_recommendation_publisher=resolve_recommendation_publisher,
    )


def _generate_recommendation(
    *,
    event: AppEvent,
    payload: Mapping[str, object],
    response_payload: dict[str, Any] | None,
    state_store: RecommendationReleaseBacklogStore,
    recommendation_runner: RecommendationRunner,
    resolve_provider_token: ResolveProviderTokenFn,
) -> MergeRecommendation | None:
    try:
        recommendation = recommendation_runner.generate(
            MergeRecommendationRequest(
                event=event,
                payload=payload,
                provider_token=resolve_provider_token(event),
            ),
        )
    except Exception as err:  # noqa: BLE001 - recommendation failures are reported to ingress
        _set_failure(
            response_payload,
            "recommendation",
            "runner_error",
            str(err).strip() or "recommendation generation failed",
        )
        return None
    if response_payload is not None:
        response_payload["recommendation"] = {
            "status": "generated",
            "label": recommendation.label,
            "current_version": recommendation.current_version,
        }
    return recommendation


def _persist_recommendation_context(
    *,
    event: AppEvent,
    payload: Mapping[str, object],
    recommendation: MergeRecommendation,
    response_payload: dict[str, Any] | None,
    state_store: RecommendationReleaseBacklogStore,
) -> str:
    body = recommendation.body
    if (
        recommendation.label is None
        or event.repository is None
        or event.pull_request_number is None
    ):
        return body
    _persist_recommendation_snapshot(event, recommendation, response_payload, state_store)
    backlog_id = _persist_release_backlog(
        event, payload, recommendation, response_payload, state_store
    )
    if backlog_id is None:
        return body
    if response_payload is not None:
        response_payload["release_backlog"] = {"status": "upserted", "id": backlog_id}
    return _apply_release_preview(event.repository, body, response_payload, state_store)


def _persist_recommendation_snapshot(
    event: AppEvent,
    recommendation: MergeRecommendation,
    response_payload: dict[str, Any] | None,
    state_store: RecommendationReleaseBacklogStore,
) -> None:
    try:
        state_store.record_recommendation_snapshot(
            repository=event.repository or "",
            pull_request_number=event.pull_request_number or 0,
            label=recommendation.label or "",
            current_version=recommendation.current_version,
            source="app_merge",
            source_event_id=event.delivery_id,
        )
    except Exception as err:  # noqa: BLE001 - persistence failures must not fail ingress
        _set_failure(
            response_payload,
            "recommendation_persistence",
            "store_error",
            str(err).strip() or "recommendation snapshot persistence failed",
        )
    else:
        if response_payload is not None:
            response_payload["recommendation_persistence"] = {"status": "stored"}


def _persist_release_backlog(
    event: AppEvent,
    payload: Mapping[str, object],
    recommendation: MergeRecommendation,
    response_payload: dict[str, Any] | None,
    state_store: RecommendationReleaseBacklogStore,
) -> int | None:
    try:
        metadata = _extract_pull_request_metadata(payload)
        return state_store.upsert_release_backlog_item(
            repository=event.repository or "",
            pull_request_number=event.pull_request_number or 0,
            merge_commit_sha=_merge_commit_sha(event),
            recommended_label=recommendation.label or "",
            recommended_current_version=recommendation.current_version,
            pull_request_title=metadata["pull_request_title"],
            pull_request_author_login=metadata["pull_request_author_login"],
            pull_request_url=metadata["pull_request_url"],
            release_summary=metadata["release_summary"],
            source_event_id=event.delivery_id,
        )
    except Exception as err:  # noqa: BLE001 - backlog failures must not fail ingress
        _set_failure(
            response_payload,
            "release_backlog",
            "store_error",
            str(err).strip() or "release backlog persistence failed",
        )
        return None


def _merge_commit_sha(event: AppEvent) -> str:
    merge_commit_sha = (event.merge_commit_sha or event.head_sha or event.base_sha or "").strip()
    return merge_commit_sha or f"unknown-pr-{event.pull_request_number}"


def _apply_release_preview(
    repository: str,
    body: str,
    response_payload: dict[str, Any] | None,
    state_store: RecommendationReleaseBacklogStore,
) -> str:
    try:
        backlog_items = state_store.list_unreleased_release_backlog_items(repository=repository)
    except Exception:  # noqa: BLE001 - preview should not fail recommendation handling
        return body
    if not backlog_items:
        return body
    aggregate = aggregate_release_backlog(backlog_items)
    if response_payload is not None:
        response_payload["release_preview"] = {
            "status": "computed",
            "baseline_version": aggregate.current_version,
            "highest_unreleased_label": aggregate.recommended_label or aggregate.aggregated_label,
            "next_version": aggregate.next_version,
        }
    return rewrite_recommendation_next_version(
        body=body,
        current_version=aggregate.current_version,
        next_version=aggregate.next_version,
    )


def _publish_recommendation(
    *,
    event: AppEvent,
    body: str,
    original_body: str,
    response_payload: dict[str, Any] | None,
    resolve_recommendation_publisher: ResolveRecommendationPublisherFn,
) -> None:
    try:
        published_url = resolve_recommendation_publisher(event).publish(
            repository=event.repository or "",
            issue_number=event.pull_request_number or 0,
            body=body or original_body,
        )
    except Exception as err:  # noqa: BLE001 - publishing failures must not fail ingress
        _set_failure(
            response_payload,
            "recommendation_delivery",
            "publisher_error",
            str(err).strip() or "recommendation publish failed",
        )
        return
    if response_payload is None:
        return
    response_payload["recommendation_delivery"] = (
        {"status": "posted", "url": published_url}
        if published_url
        else {"status": "skipped", "reason": "publisher_unavailable"}
    )


def _set_failure(
    response_payload: dict[str, Any] | None,
    key: str,
    reason: str,
    message: str,
) -> None:
    if response_payload is not None:
        response_payload[key] = {"status": "failed", "reason": reason, "message": message}


def rewrite_recommendation_next_version(
    *,
    body: str,
    current_version: str | None,
    next_version: str | None,
) -> str:
    normalized_current = _normalize_version_token(current_version or "")
    normalized_next = _normalize_version_token(next_version or "")
    if normalized_current is None or normalized_next is None:
        return body
    line = f"Next version   : v{normalized_current} -> v{normalized_next}"
    if _NEXT_VERSION_LINE_RE.search(body):
        updated = _NEXT_VERSION_LINE_RE.sub(line, body, count=1)
    else:
        suffix = "" if body.endswith("\n") else "\n"
        updated = f"{body}{suffix}{line}\n"
    return updated if updated.endswith("\n") else f"{updated}\n"
