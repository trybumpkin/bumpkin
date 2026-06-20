from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from bumpkin.integrations.github.events import (
    is_recommendation_merge_event,
    normalize_webhook_event,
)
from bumpkin.integrations.github.persistence import AppStateStore
from bumpkin.integrations.github.reactions import (
    GitHubIssueCommentPublisher,
    GitHubIssueCommentReactionPublisher,
    ReactionPublisher,
    ReactionPublishRequest,
)
from bumpkin.integrations.github.recommendations import (
    MergeRecommendationRequest,
    RecommendationPublisher,
    RecommendationRunner,
)
from bumpkin.integrations.github.release_aggregation import aggregate_release_backlog
from bumpkin.integrations.github.types import AppEvent
from bumpkin.integrations.github.webhook_parsing import (
    _extract_pull_request_metadata,
    _normalize_version_token,
)

_DEFERRED_DEPLOY_STATUS_PREFIX = "deferred_deploy:"
_NEXT_VERSION_LINE_RE = re.compile(r"(?im)^next version\s*:\s*.*$")

ResolveProviderTokenFn = Callable[[AppEvent | None], str | None]
ResolveRecommendationPublisherFn = Callable[[AppEvent | None], RecommendationPublisher]
ReactionPublisherFactory = Callable[[str], ReactionPublisher]
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
                recommendation_body = rewrite_recommendation_next_version(
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
    if not updated.endswith("\n"):
        updated += "\n"
    return updated


def publish_command_reaction(
    *,
    event: AppEvent,
    command_name: str,
    command_args: tuple[str, ...],
    command_raw: str,
    reaction: dict[str, Any],
    response_payload: dict[str, Any],
    configured_reaction_publisher: ReactionPublisher | None,
    default_reaction_publisher: ReactionPublisher,
    resolve_provider_token: ResolveProviderTokenFn,
    publisher_factory: ReactionPublisherFactory,
) -> None:
    if event.repository is None:
        return

    publish_request = ReactionPublishRequest(
        repository=event.repository,
        issue_number=event.pull_request_number or 0,
        command_name=command_name,
        command_args=command_args,
        command_raw=command_raw,
        reaction=reaction,
        comment_id=event.comment_id,
        comment_html_url=event.comment_html_url,
        installation_id=event.installation_id,
    )
    try:
        reaction_publisher = configured_reaction_publisher
        if reaction_publisher is None:
            token = resolve_provider_token(event)
            if token is not None:
                reaction_publisher = publisher_factory(token)
            else:
                reaction_publisher = default_reaction_publisher
        published_url = reaction_publisher.publish(publish_request)
    except Exception as err:  # noqa: BLE001 - reaction delivery must not fail webhook intake
        response_payload["reaction_delivery"] = {
            "status": "failed",
            "reason": "publisher_error",
            "message": str(err).strip() or "reaction publish failed",
        }
        return
    if published_url:
        response_payload["reaction_delivery"] = {
            "status": "posted",
            "url": published_url,
        }


def publish_shell_command_reaction(
    *,
    event: AppEvent,
    command_name: str,
    command_args: tuple[str, ...],
    command_raw: str,
    reaction: dict[str, Any],
    response_payload: dict[str, Any],
    configured_reaction_publisher: ReactionPublisher | None,
    default_reaction_publisher: ReactionPublisher,
    resolve_provider_token: ResolveProviderTokenFn,
) -> None:
    publish_command_reaction(
        event=event,
        command_name=command_name,
        command_args=command_args,
        command_raw=command_raw,
        reaction=reaction,
        response_payload=response_payload,
        configured_reaction_publisher=configured_reaction_publisher,
        default_reaction_publisher=default_reaction_publisher,
        resolve_provider_token=resolve_provider_token,
        publisher_factory=lambda token: GitHubIssueCommentReactionPublisher(token=token),
    )


def publish_issue_comment_reaction(
    *,
    event: AppEvent,
    command_name: str,
    command_args: tuple[str, ...],
    command_raw: str,
    reaction: dict[str, Any],
    response_payload: dict[str, Any],
    configured_reaction_publisher: ReactionPublisher | None,
    default_reaction_publisher: ReactionPublisher,
    resolve_provider_token: ResolveProviderTokenFn,
) -> None:
    publish_command_reaction(
        event=event,
        command_name=command_name,
        command_args=command_args,
        command_raw=command_raw,
        reaction=reaction,
        response_payload=response_payload,
        configured_reaction_publisher=configured_reaction_publisher,
        default_reaction_publisher=default_reaction_publisher,
        resolve_provider_token=resolve_provider_token,
        publisher_factory=lambda token: GitHubIssueCommentPublisher(token=token),
    )


__all__ = [
    "build_event_payload",
    "deferred_status_value",
    "has_pending_self_deferred_merge_for_current_deploy",
    "process_merge_recommendation",
    "publish_issue_comment_reaction",
    "publish_shell_command_reaction",
    "replay_deferred_merge_recommendations_once",
    "rewrite_recommendation_next_version",
    "should_defer_merge_recommendation",
]
