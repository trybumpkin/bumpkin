from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from bumpkin.integrations.github.persistence_protocols import (
    RecommendationReleaseBacklogStore,
    ReleaseBacklogPersistenceStore,
)
from bumpkin.integrations.github.release_aggregation import aggregate_release_backlog
from bumpkin.integrations.github.release_notes import render_release_notes
from bumpkin.integrations.github.releases import ReleasePublisher, ReleasePublishRequest
from bumpkin.integrations.github.runtime import AppRuntimeConfig
from bumpkin.integrations.github.tags import TagPublisher, TagPublishRequest
from bumpkin.integrations.github.types import AppEvent, SlashCommand
from bumpkin.integrations.github.webhook_commands import (
    _build_command_reaction,
    _mark_bump_not_applied_when_tag_failed,
    _resolve_shell_operation,
)
from bumpkin.integrations.github.webhook_parsing import _extract_repository_default_branch
from bumpkin.integrations.github.workflows import WorkflowDispatcher, WorkflowDispatchRequest

ResolveTagPublisherFn = Callable[[AppEvent | None], TagPublisher]
ResolveReleasePublisherFn = Callable[[AppEvent | None], ReleasePublisher]


def dispatch_release_workflow_command(
    *,
    event: AppEvent,
    payload: Mapping[str, object],
    command: SlashCommand,
    response_payload: dict[str, Any],
    config: AppRuntimeConfig,
    dispatcher: WorkflowDispatcher,
) -> None:
    if event.repository is None:
        response_payload["reaction"] = {
            "type": "workflow_dispatch_requested",
            "applied": False,
            "message": "Cannot dispatch a release workflow without a repository context.",
        }
        return

    operation, error_message = _resolve_shell_operation(command)
    if operation is None:
        response_payload["reaction"] = {
            "type": "workflow_dispatch_requested",
            "applied": False,
            "message": error_message or "Unsupported shell command.",
        }
        return

    base_tag = _extract_shell_base_tag(command)
    dispatch_ref = (
        _extract_repository_default_branch(payload)
        or config.release_workflow_ref
        or event.base_ref
        or "main"
    )
    request = WorkflowDispatchRequest(
        repository=event.repository,
        workflow_id=config.release_workflow_file,
        ref=dispatch_ref,
        operation=operation,
        base_tag=base_tag,
        installation_id=event.installation_id,
    )
    try:
        result = dispatcher.dispatch(request)
    except Exception as err:  # noqa: BLE001 - dispatch failures should not fail ingress
        response_payload["workflow_dispatch"] = {
            "status": "failed",
            "reason": "dispatcher_error",
            "workflow_id": request.workflow_id,
            "operation": request.operation,
            "ref": request.ref,
            "message": str(err).strip() or "workflow dispatch failed",
        }
        response_payload["reaction"] = {
            "type": "workflow_dispatch_requested",
            "applied": False,
            "workflow_id": request.workflow_id,
            "operation": request.operation,
            "ref": request.ref,
            "base_tag": request.base_tag,
            "message": response_payload["workflow_dispatch"]["message"],
        }
        return

    response_payload["workflow_dispatch"] = {
        "status": result.status,
        "workflow_id": result.workflow_id,
        "operation": result.operation,
        "ref": result.ref,
    }
    if result.base_tag:
        response_payload["workflow_dispatch"]["base_tag"] = result.base_tag
    if result.url:
        response_payload["workflow_dispatch"]["url"] = result.url
    if result.message:
        response_payload["workflow_dispatch"]["message"] = result.message

    response_payload["reaction"] = {
        "type": "workflow_dispatch_requested",
        "applied": result.status == "queued",
        "workflow_id": result.workflow_id,
        "operation": result.operation,
        "ref": result.ref,
        "base_tag": result.base_tag,
        "workflow_url": result.url,
        "message": result.message
        or (
            "Queued release preview workflow."
            if result.operation == "release_preview"
            else "Queued release publish workflow."
        ),
    }


def process_release_command(
    *,
    event: AppEvent,
    response_payload: dict[str, Any],
    state_store: ReleaseBacklogPersistenceStore,
    resolve_tag_publisher: ResolveTagPublisherFn,
    resolve_release_publisher: ResolveReleasePublisherFn,
) -> None:
    if event.repository is None:
        response_payload["release"] = {
            "status": "failed",
            "reason": "missing_repository",
        }
        return

    try:
        backlog_items = state_store.list_unreleased_release_backlog_items(
            repository=event.repository,
        )
    except Exception:  # noqa: BLE001 - backlog read errors should not fail release handling
        backlog_items = []

    response_payload["release_backlog"] = {
        "status": "loaded",
        "items": len(backlog_items),
    }
    if not backlog_items:
        response_payload["release"] = {
            "status": "skipped",
            "reason": "no_unreleased_items",
        }
        return

    aggregate = aggregate_release_backlog(backlog_items)
    release_label = aggregate.recommended_label or aggregate.aggregated_label
    current_version = aggregate.current_version
    next_version = aggregate.next_version
    if not next_version:
        response_payload["release"] = {
            "status": "skipped",
            "reason": "missing_next_version",
        }
        return

    tag_name = f"v{next_version}"
    target_sha = (
        (aggregate.target_merge_commit_sha or "").strip()
        or (event.merge_commit_sha or "").strip()
        or (event.head_sha or "").strip()
        or (event.base_sha or "").strip()
    )
    if not target_sha:
        response_payload["release"] = {
            "status": "skipped",
            "reason": "missing_target_sha",
        }
        return

    release_notes = render_release_notes(
        tag_name=tag_name,
        items=backlog_items,
        current_version=current_version,
        next_version=next_version,
        release_label=release_label,
    )
    response_payload["release_notes"] = {
        "status": "rendered",
        "tag_name": tag_name,
        "included_prs": len(backlog_items),
        "release_label": release_label,
    }

    tag_request = TagPublishRequest(
        repository=event.repository,
        tag_name=tag_name,
        target_sha=target_sha,
        installation_id=event.installation_id,
    )
    try:
        tag_result = resolve_tag_publisher(event).publish(tag_request)
    except Exception as err:  # noqa: BLE001 - tag publish failures should not fail webhook intake
        response_payload["tag_delivery"] = {
            "status": "failed",
            "reason": "publisher_error",
            "message": str(err).strip() or "tag publish failed",
        }
        response_payload["release"] = {
            "status": "failed",
            "reason": "tag_publish_failed",
        }
        return

    response_payload["tag_delivery"] = {
        "status": tag_result.status,
        "tag_name": tag_result.tag_name,
        "target_sha": target_sha,
    }
    if tag_result.url:
        response_payload["tag_delivery"]["url"] = tag_result.url
    if tag_result.message:
        response_payload["tag_delivery"]["message"] = tag_result.message
    if tag_result.status not in {"created", "exists"}:
        response_payload["release"] = {
            "status": "skipped",
            "reason": "tag_publish_skipped",
        }
        return

    release_request = ReleasePublishRequest(
        repository=event.repository,
        tag_name=tag_name,
        target_sha=target_sha,
        body=release_notes,
        name=tag_name,
        installation_id=event.installation_id,
    )
    try:
        release_result = resolve_release_publisher(event).publish(release_request)
    except Exception as err:  # noqa: BLE001 - release publish failures should not fail webhook intake
        response_payload["release_delivery"] = {
            "status": "failed",
            "reason": "publisher_error",
            "message": str(err).strip() or "release publish failed",
        }
        response_payload["release"] = {
            "status": "failed",
            "reason": "release_publish_failed",
        }
        return

    response_payload["release_delivery"] = {
        "status": release_result.status,
        "tag_name": release_result.tag_name,
    }
    if release_result.url:
        response_payload["release_delivery"]["url"] = release_result.url
    if release_result.message:
        response_payload["release_delivery"]["message"] = release_result.message

    if release_result.status in {"created", "updated"}:
        try:
            included_count = state_store.mark_release_backlog_items_included(
                repository=event.repository,
                backlog_ids=aggregate.considered_item_ids,
                release_tag=tag_name,
            )
        except Exception as err:  # noqa: BLE001 - inclusion failures should not fail webhook intake
            response_payload["release_backlog_update"] = {
                "status": "failed",
                "reason": "store_error",
                "message": str(err).strip() or "release backlog inclusion update failed",
            }
        else:
            response_payload["release_backlog_update"] = {
                "status": "marked_included",
                "release_tag": tag_name,
                "updated_count": included_count,
            }

    response_payload["release"] = {
        "status": "published",
        "tag_name": tag_name,
        "release_url": release_result.url or response_payload["release_delivery"].get("url"),
        "included_prs": len(backlog_items),
    }


def process_bump_command_release_side_effects(
    *,
    event: AppEvent,
    command: SlashCommand,
    response_payload: dict[str, Any],
    state_store: RecommendationReleaseBacklogStore,
    mismatch_policy: str,
    resolve_tag_publisher: ResolveTagPublisherFn,
) -> None:
    recommended_label: str | None = None
    recommended_current_version: str | None = None
    release_backlog_ids_to_include: tuple[int, ...] = ()
    release_target_merge_sha: str | None = None

    if event.repository is not None and event.pull_request_number is not None:
        try:
            backlog_items = state_store.list_unreleased_release_backlog_items(
                repository=event.repository,
            )
        except Exception:  # noqa: BLE001 - backlog read errors should not fail command handling
            backlog_items = []
        if backlog_items:
            aggregate = aggregate_release_backlog(backlog_items)
            recommended_label = aggregate.recommended_label or aggregate.aggregated_label
            recommended_current_version = aggregate.current_version
            release_backlog_ids_to_include = aggregate.considered_item_ids
            release_target_merge_sha = aggregate.target_merge_commit_sha
            response_payload["release_backlog"] = {
                "status": "loaded",
                "items": aggregate.item_count,
                "considered_items": aggregate.considered_item_count,
                "considered_backlog_ids": list(aggregate.considered_item_ids),
                "aggregated_label": aggregate.aggregated_label,
                "recommended_label": aggregate.recommended_label,
                "baseline_version": aggregate.baseline_version,
                "current_version": aggregate.current_version,
                "next_version": aggregate.next_version,
                "target_merge_commit_sha": aggregate.target_merge_commit_sha,
            }
        if recommended_label is None or recommended_current_version is None:
            recommendation = state_store.latest_recommendation_for_pr(
                repository=event.repository,
                pull_request_number=event.pull_request_number,
            )
            if recommendation is not None:
                if recommended_label is None:
                    recommended_label = recommendation.label
                if recommended_current_version is None:
                    recommended_current_version = recommendation.current_version

    reaction = _build_command_reaction(
        command,
        recommended_label=recommended_label,
        recommended_current_version=recommended_current_version,
        mismatch_policy=mismatch_policy,
    )
    response_payload["reaction"] = reaction

    if not bool(reaction.get("applied")):
        return

    next_version = str(reaction.get("next_version", "")).strip()
    tag_name = f"v{next_version}" if next_version else ""
    target_sha = (
        (release_target_merge_sha or "").strip()
        or (event.merge_commit_sha or "").strip()
        or (event.head_sha or "").strip()
        or (event.base_sha or "").strip()
    )
    if not tag_name:
        response_payload["tag_delivery"] = {
            "status": "skipped",
            "reason": "missing_next_version",
        }
    elif not target_sha:
        response_payload["tag_delivery"] = {
            "status": "skipped",
            "reason": "missing_target_sha",
        }
    else:
        tag_request = TagPublishRequest(
            repository=event.repository or "",
            tag_name=tag_name,
            target_sha=target_sha,
            installation_id=event.installation_id,
        )
        try:
            tag_result = resolve_tag_publisher(event).publish(tag_request)
        except Exception as err:  # noqa: BLE001 - tag publish failures should not fail webhook intake
            response_payload["tag_delivery"] = {
                "status": "failed",
                "reason": "publisher_error",
                "message": str(err).strip() or "tag publish failed",
            }
        else:
            response_payload["tag_delivery"] = {
                "status": tag_result.status,
                "tag_name": tag_result.tag_name,
                "target_sha": target_sha,
            }
            if tag_result.url:
                response_payload["tag_delivery"]["url"] = tag_result.url
            if tag_result.message:
                response_payload["tag_delivery"]["message"] = tag_result.message
            if tag_result.status in {"created", "exists"} and release_backlog_ids_to_include:
                try:
                    included_count = state_store.mark_release_backlog_items_included(
                        repository=event.repository or "",
                        backlog_ids=release_backlog_ids_to_include,
                        release_tag=tag_name,
                    )
                except Exception as err:  # noqa: BLE001 - inclusion failures should not fail webhook intake
                    response_payload["release_backlog_update"] = {
                        "status": "failed",
                        "reason": "store_error",
                        "message": str(err).strip() or "release backlog inclusion update failed",
                    }
                else:
                    response_payload["release_backlog_update"] = {
                        "status": "marked_included",
                        "release_tag": tag_name,
                        "updated_count": included_count,
                    }

    response_payload["reaction"] = _mark_bump_not_applied_when_tag_failed(
        reaction=reaction,
        tag_delivery=response_payload.get("tag_delivery"),
    )


def build_release_command_reaction(response_payload: Mapping[str, object]) -> dict[str, Any]:
    release = response_payload.get("release")
    release_mapping = release if isinstance(release, Mapping) else {}
    release_status = str(release_mapping.get("status", "")).strip()
    return {
        "type": "release_published" if release_status == "published" else "release_cut",
        "applied": release_status == "published",
        "tag_name": release_mapping.get("tag_name"),
        "release_url": release_mapping.get("release_url"),
        "included_prs": release_mapping.get("included_prs"),
        "message": (
            f"Published release {release_mapping.get('tag_name')}"
            if release_status == "published"
            else str(release_mapping.get("reason", "release not published"))
        ),
    }


def _extract_shell_base_tag(command: SlashCommand) -> str | None:
    if command.name == "publish":
        remaining_args = command.args
    elif command.args and command.args[0].strip().lower() in {"publish", "cut", "preview"}:
        remaining_args = command.args[1:]
    else:
        remaining_args = command.args
    if not remaining_args:
        return None
    return remaining_args[0].strip() or None


__all__ = [
    "build_release_command_reaction",
    "dispatch_release_workflow_command",
    "process_bump_command_release_side_effects",
    "process_release_command",
]
