from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from bumpkin.integrations.github.persistence_protocols import RecommendationReleaseBacklogStore
from bumpkin.integrations.github.reactions import ReactionPublisher
from bumpkin.integrations.github.types import AppEvent, SlashCommand
from bumpkin.integrations.github.webhook_commands import _build_command_reaction
from bumpkin.integrations.github.webhook_commands import (
    _is_release_command as _is_release_command_impl,
)
from bumpkin.integrations.github.webhook_release_flow import (
    build_release_command_reaction,
    process_bump_command_release_side_effects,
)
from bumpkin.integrations.github.webhook_service_commands import build_command_payload
from bumpkin.integrations.github.webhook_service_reactions import (
    publish_issue_comment_reaction,
    publish_shell_command_reaction,
)
from bumpkin.integrations.github.webhook_service_types import (
    ProcessReleaseCommandFn,
    ProcessShellCommandFn,
    ResolveProviderTokenFn,
    ResolveTagPublisherFn,
)


def handle_shell_mode_command(
    *,
    event: AppEvent | None,
    payload: Mapping[str, object],
    command: SlashCommand,
    response_payload: dict[str, Any],
    configured_reaction_publisher: ReactionPublisher | None,
    default_reaction_publisher: ReactionPublisher,
    resolve_provider_token: ResolveProviderTokenFn,
    process_shell_command_fn: ProcessShellCommandFn,
) -> None:
    response_payload["command"] = build_command_payload(command)
    if event is None:
        response_payload["reaction"] = {
            "type": "workflow_dispatch_requested",
            "applied": False,
            "message": "Shell commands require repository context.",
        }
        return
    process_shell_command_fn(event, payload, command, response_payload)
    if event.repository is None:
        return
    publish_shell_command_reaction(
        event=event,
        command_name=command.name,
        command_args=command.args,
        command_raw=command.raw,
        reaction=response_payload["reaction"],
        response_payload=response_payload,
        configured_reaction_publisher=configured_reaction_publisher,
        default_reaction_publisher=default_reaction_publisher,
        resolve_provider_token=resolve_provider_token,
    )


def handle_issue_comment_command(
    *,
    event: AppEvent | None,
    command: SlashCommand,
    response_payload: dict[str, Any],
    mismatch_policy: str,
    state_store: RecommendationReleaseBacklogStore,
    resolve_tag_publisher: ResolveTagPublisherFn,
    process_release_command_fn: ProcessReleaseCommandFn,
    configured_reaction_publisher: ReactionPublisher | None,
    default_reaction_publisher: ReactionPublisher,
    resolve_provider_token: ResolveProviderTokenFn,
) -> None:
    response_payload["command"] = build_command_payload(command)
    _apply_issue_comment_command(
        event=event,
        command=command,
        response_payload=response_payload,
        mismatch_policy=mismatch_policy,
        state_store=state_store,
        resolve_tag_publisher=resolve_tag_publisher,
        process_release_command_fn=process_release_command_fn,
    )
    if event is None or event.repository is None:
        return
    publish_issue_comment_reaction(
        event=event,
        command_name=command.name,
        command_args=command.args,
        command_raw=command.raw,
        reaction=response_payload["reaction"],
        response_payload=response_payload,
        configured_reaction_publisher=configured_reaction_publisher,
        default_reaction_publisher=default_reaction_publisher,
        resolve_provider_token=resolve_provider_token,
    )


def _apply_issue_comment_command(
    *,
    event: AppEvent | None,
    command: SlashCommand,
    response_payload: dict[str, Any],
    mismatch_policy: str,
    state_store: RecommendationReleaseBacklogStore,
    resolve_tag_publisher: ResolveTagPublisherFn,
    process_release_command_fn: ProcessReleaseCommandFn,
) -> None:
    if _is_release_command_impl(command):
        if event is not None and event.repository is not None:
            process_release_command_fn(event, response_payload)
        response_payload["reaction"] = build_release_command_reaction(response_payload)
        return
    if event is not None and _is_bump_command_context(event, command):
        process_bump_command_release_side_effects(
            event=event,
            command=command,
            response_payload=response_payload,
            state_store=state_store,
            mismatch_policy=mismatch_policy,
            resolve_tag_publisher=resolve_tag_publisher,
        )
        return
    response_payload["reaction"] = _build_command_reaction(
        command,
        recommended_label=None,
        recommended_current_version=None,
        mismatch_policy=mismatch_policy,
    )


def _is_bump_command_context(event: AppEvent, command: SlashCommand) -> bool:
    return (
        command.name == "bump"
        and event.repository is not None
        and event.pull_request_number is not None
    )
