from __future__ import annotations

from typing import Any

from bumpkin.integrations.github.reactions import (
    GitHubIssueCommentPublisher,
    GitHubIssueCommentReactionPublisher,
    ReactionPublisher,
    ReactionPublishRequest,
)
from bumpkin.integrations.github.types import AppEvent
from bumpkin.integrations.github.webhook_service_types import (
    ReactionPublisherFactory,
    ResolveProviderTokenFn,
)


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
            reaction_publisher = (
                publisher_factory(token) if token is not None else default_reaction_publisher
            )
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
