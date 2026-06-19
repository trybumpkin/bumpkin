from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, Self

from bumpkin.integrations.github.events import (
    is_recommendation_merge_event,
)
from bumpkin.integrations.github.github_auth import GitHubAppInstallationTokenProvider
from bumpkin.integrations.github.ingress import (
    DeliveryStore,
    InMemoryDeliveryStore,
    ingest_webhook_event,
)
from bumpkin.integrations.github.persistence import (
    AppStateStore,
    EphemeralAppStateStore,
    build_app_state_store,
)
from bumpkin.integrations.github.reactions import (
    GitHubIssueCommentPublisher,
    GitHubIssueCommentReactionPublisher,
    NoopReactionPublisher,
    ReactionPublisher,
    ReactionPublishRequest,
)
from bumpkin.integrations.github.recommendations import (
    GitHubRecommendationCommentPublisher,
    NoopRecommendationPublisher,
    PipelineRecommendationRunner,
    RecommendationPublisher,
    RecommendationRunner,
)
from bumpkin.integrations.github.releases import (
    GitHubReleasePublisher,
    NoopReleasePublisher,
    ReleasePublisher,
)
from bumpkin.integrations.github.runtime import (
    APP_MODE_SHELL,
    AppRuntimeConfig,
    load_app_runtime_config,
)
from bumpkin.integrations.github.tags import (
    GitHubTagPublisher,
    NoopTagPublisher,
    TagPublisher,
)
from bumpkin.integrations.github.types import AppEvent, SlashCommand
from bumpkin.integrations.github.webhook_commands import (
    _build_command_reaction as _build_command_reaction_impl,
)
from bumpkin.integrations.github.webhook_commands import (
    _bump_semver as _bump_semver_impl,
)
from bumpkin.integrations.github.webhook_commands import (
    _is_release_command as _is_release_command_impl,
)
from bumpkin.integrations.github.webhook_commands import (
    _is_shell_mode as _is_shell_mode_impl,
)
from bumpkin.integrations.github.webhook_commands import (
    _mark_bump_not_applied_when_tag_failed as _mark_bump_not_applied_when_tag_failed_impl,
)
from bumpkin.integrations.github.webhook_commands import (
    _parse_bump_command_args as _parse_bump_command_args_impl,
)
from bumpkin.integrations.github.webhook_commands import (
    _resolve_shell_operation as _resolve_shell_operation_impl,
)
from bumpkin.integrations.github.webhook_parsing import (
    _normalize_headers,
    _normalize_version_token,
    _status_for_outcome,
)
from bumpkin.integrations.github.webhook_release_flow import (
    build_release_command_reaction,
    dispatch_release_workflow_command,
    process_bump_command_release_side_effects,
)
from bumpkin.integrations.github.webhook_release_flow import (
    process_release_command as _process_release_command_impl,
)
from bumpkin.integrations.github.webhook_service import (
    build_event_payload,
)
from bumpkin.integrations.github.webhook_service import (
    deferred_status_value as _deferred_status_value_impl,
)
from bumpkin.integrations.github.webhook_service import (
    has_pending_self_deferred_merge_for_current_deploy as _has_pending_self_deferred_merge_for_current_deploy_impl,
)
from bumpkin.integrations.github.webhook_service import (
    process_merge_recommendation as _process_merge_recommendation_impl,
)
from bumpkin.integrations.github.webhook_service import (
    replay_deferred_merge_recommendations_once as _replay_deferred_merge_recommendations_once_impl,
)
from bumpkin.integrations.github.webhook_service import (
    should_defer_merge_recommendation as _should_defer_merge_recommendation_impl,
)
from bumpkin.integrations.github.workflows import (
    GitHubWorkflowDispatcher,
    NoopWorkflowDispatcher,
    WorkflowDispatcher,
)

_HEADER_EVENT_NAME = "x-github-event"
_NEXT_VERSION_LINE_RE = re.compile(r"(?im)^next version\s*:\s*.*$")
_DEFERRED_DEPLOY_STATUS_PREFIX = "deferred_deploy:"


@dataclass(frozen=True, slots=True)
class WebhookResponse:
    status_code: int
    payload: dict[str, Any]


class InstallationTokenProvider(Protocol):
    def get_token(self, installation_id: int | None) -> str | None: ...


def _bump_semver(version: str, label: str) -> str:
    return _bump_semver_impl(version, label)


def _rewrite_recommendation_next_version(
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


def _parse_bump_command_args(args: tuple[str, ...]) -> tuple[str, str | None, bool, bool]:
    return _parse_bump_command_args_impl(args)


def _build_command_reaction(
    command: SlashCommand,
    *,
    recommended_label: str | None = None,
    recommended_current_version: str | None = None,
    mismatch_policy: str,
) -> dict[str, Any]:
    return _build_command_reaction_impl(
        command,
        recommended_label=recommended_label,
        recommended_current_version=recommended_current_version,
        mismatch_policy=mismatch_policy,
    )


def _mark_bump_not_applied_when_tag_failed(
    *,
    reaction: dict[str, Any],
    tag_delivery: Mapping[str, object] | None,
) -> dict[str, Any]:
    return _mark_bump_not_applied_when_tag_failed_impl(
        reaction=reaction,
        tag_delivery=tag_delivery,
    )


def _is_release_command(command: SlashCommand) -> bool:
    return _is_release_command_impl(command)


def _is_shell_mode(config: AppRuntimeConfig) -> bool:
    return _is_shell_mode_impl(config)


def _resolve_shell_operation(command: SlashCommand) -> tuple[str | None, str | None]:
    return _resolve_shell_operation_impl(command)


class AppWebhookService:
    def __init__(
        self,
        *,
        config: AppRuntimeConfig,
        state_store: AppStateStore,
        delivery_store: DeliveryStore | None = None,
        reaction_publisher: ReactionPublisher | None = None,
        tag_publisher: TagPublisher | None = None,
        release_publisher: ReleasePublisher | None = None,
        recommendation_runner: RecommendationRunner | None = None,
        recommendation_publisher: RecommendationPublisher | None = None,
        installation_token_provider: InstallationTokenProvider | None = None,
        workflow_dispatcher: WorkflowDispatcher | None = None,
    ) -> None:
        self._config = config
        self._shell_mode = _is_shell_mode(config)
        self._state_store = state_store
        self._delivery_store = delivery_store or InMemoryDeliveryStore()
        self._recommendation_runner = recommendation_runner or PipelineRecommendationRunner()
        self._reaction_publisher = reaction_publisher
        self._tag_publisher = tag_publisher
        self._release_publisher = release_publisher
        self._recommendation_publisher = recommendation_publisher
        self._workflow_dispatcher = workflow_dispatcher
        if installation_token_provider is not None:
            self._installation_token_provider = installation_token_provider
        elif config.github_app_id and config.github_app_private_key:
            self._installation_token_provider = GitHubAppInstallationTokenProvider(
                app_id=config.github_app_id,
                private_key_pem=config.github_app_private_key,
            )
        else:
            self._installation_token_provider = None
        self._default_reaction_publisher = NoopReactionPublisher()
        self._default_tag_publisher = NoopTagPublisher()
        self._default_release_publisher = NoopReleasePublisher()
        self._default_recommendation_publisher = NoopRecommendationPublisher()
        self._self_repository = (config.self_repository or "").strip().lower() or None
        self._deployment_revision = (config.deployment_revision or "").strip() or None
        self._defer_self_merge_recommendation = (
            config.defer_self_merge_recommendation_until_new_deploy
        )
        if not self._shell_mode:
            self._replay_deferred_merge_recommendations_once()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def close(self) -> None:
        self._state_store.close()

    def _resolve_provider_token(self, event: AppEvent | None) -> str | None:
        if self._installation_token_provider is not None and event is not None:
            app_token = self._installation_token_provider.get_token(event.installation_id)
            if app_token is not None:
                return app_token
        return self._config.provider_token

    def _resolve_workflow_dispatcher(self, event: AppEvent | None) -> WorkflowDispatcher:
        if self._workflow_dispatcher is not None:
            return self._workflow_dispatcher
        token = self._resolve_provider_token(event)
        if token is not None:
            return GitHubWorkflowDispatcher(token=token)
        return NoopWorkflowDispatcher()

    def _resolve_tag_publisher(self, event: AppEvent | None) -> TagPublisher:
        if self._tag_publisher is not None:
            return self._tag_publisher
        token = self._resolve_provider_token(event)
        if token is not None:
            return GitHubTagPublisher(token=token)
        return self._default_tag_publisher

    def _resolve_release_publisher(self, event: AppEvent | None) -> ReleasePublisher:
        if self._release_publisher is not None:
            return self._release_publisher
        token = self._resolve_provider_token(event)
        if token is not None:
            return GitHubReleasePublisher(token=token)
        return self._default_release_publisher

    def _resolve_recommendation_publisher(self, event: AppEvent | None) -> RecommendationPublisher:
        if self._recommendation_publisher is not None:
            return self._recommendation_publisher
        token = self._resolve_provider_token(event)
        if token is not None:
            return GitHubRecommendationCommentPublisher(token=token)
        return self._default_recommendation_publisher

    def _deferred_status_value(self) -> str:
        return _deferred_status_value_impl(self._deployment_revision)

    def _should_defer_merge_recommendation(self, event: AppEvent) -> bool:
        return _should_defer_merge_recommendation_impl(
            event,
            defer_self_merge_recommendation=self._defer_self_merge_recommendation,
            self_repository=self._self_repository,
            deployment_revision=self._deployment_revision,
        )

    def _replay_deferred_merge_recommendations_once(self) -> None:
        _replay_deferred_merge_recommendations_once_impl(
            defer_self_merge_recommendation=self._defer_self_merge_recommendation,
            self_repository=self._self_repository,
            deployment_revision=self._deployment_revision,
            state_store=self._state_store,
            process_merge_recommendation_fn=lambda event, payload, response_payload: (
                self._process_merge_recommendation(
                    event=event,
                    payload=payload,
                    response_payload=response_payload,
                )
            ),
        )

    def _has_pending_self_deferred_merge_for_current_deploy(self) -> bool:
        return _has_pending_self_deferred_merge_for_current_deploy_impl(
            defer_self_merge_recommendation=self._defer_self_merge_recommendation,
            self_repository=self._self_repository,
            deployment_revision=self._deployment_revision,
            state_store=self._state_store,
        )

    def _process_merge_recommendation(
        self,
        *,
        event: AppEvent,
        payload: Mapping[str, object],
        response_payload: dict[str, Any] | None,
    ) -> None:
        _process_merge_recommendation_impl(
            event=event,
            payload=payload,
            response_payload=response_payload,
            state_store=self._state_store,
            recommendation_runner=self._recommendation_runner,
            resolve_provider_token=self._resolve_provider_token,
            resolve_recommendation_publisher=self._resolve_recommendation_publisher,
        )

    def _process_shell_command(
        self,
        *,
        event: AppEvent,
        payload: Mapping[str, object],
        command: SlashCommand,
        response_payload: dict[str, Any],
    ) -> None:
        dispatch_release_workflow_command(
            event=event,
            payload=payload,
            command=command,
            response_payload=response_payload,
            config=self._config,
            dispatcher=self._resolve_workflow_dispatcher(event),
        )

    def _process_release_command(
        self,
        *,
        event: AppEvent,
        response_payload: dict[str, Any],
    ) -> None:
        _process_release_command_impl(
            event=event,
            response_payload=response_payload,
            state_store=self._state_store,
            resolve_tag_publisher=self._resolve_tag_publisher,
            resolve_release_publisher=self._resolve_release_publisher,
        )

    def handle_github_webhook(
        self,
        *,
        headers: Mapping[str, object],
        raw_body: bytes,
    ) -> WebhookResponse:
        normalized_headers = _normalize_headers(headers)
        event_name = normalized_headers.get(_HEADER_EVENT_NAME, "").strip()
        if not event_name:
            return WebhookResponse(
                status_code=400,
                payload={
                    "accepted": False,
                    "outcome": "invalid_request",
                    "reason": "missing_event_name",
                },
            )

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return WebhookResponse(
                status_code=400,
                payload={
                    "accepted": False,
                    "outcome": "invalid_request",
                    "reason": "invalid_payload_json",
                },
            )
        if not isinstance(payload, dict):
            return WebhookResponse(
                status_code=400,
                payload={
                    "accepted": False,
                    "outcome": "invalid_request",
                    "reason": "payload_must_be_object",
                },
            )

        result = ingest_webhook_event(
            provider="github",
            event_name=event_name,
            payload=payload,
            headers=headers,
            webhook_secret=self._config.webhook_secret,
            delivery_store=self._delivery_store,
            event_store=self._state_store,
            raw_body=raw_body,
        )
        response_payload: dict[str, Any] = {
            "accepted": result.accepted,
            "outcome": result.outcome,
            "reason": result.reason,
        }
        if result.event is not None:
            response_payload["event"] = build_event_payload(result.event)
        if (
            result.event is not None
            and result.envelope is not None
            and is_recommendation_merge_event(result.event)
        ):
            if self._shell_mode:
                response_payload["recommendation"] = {
                    "status": "skipped",
                    "reason": "shell_mode_release_scoped",
                }
            elif self._should_defer_merge_recommendation(result.event):
                deferred_status = self._deferred_status_value()
                updated = False
                if result.event.delivery_id is not None:
                    updated = self._state_store.update_event_status(
                        provider="github",
                        provider_event_id=result.event.delivery_id,
                        status=deferred_status,
                    )
                response_payload["recommendation"] = {
                    "status": "deferred",
                    "reason": "awaiting_new_deploy",
                    "deployment_revision": self._deployment_revision,
                }
                response_payload["recommendation_defer"] = {
                    "status": "recorded" if updated else "not_recorded",
                    "event_status": deferred_status,
                }
            else:
                self._process_merge_recommendation(
                    event=result.event,
                    payload=result.envelope.payload,
                    response_payload=response_payload,
                )
        if (
            not self._shell_mode
            and result.command is not None
            and result.event is not None
            and result.event.repository is not None
            and self._self_repository is not None
            and self._deployment_revision is not None
            and result.event.repository.strip().lower() == self._self_repository
            and self._has_pending_self_deferred_merge_for_current_deploy()
        ):
            response_payload["command"] = {
                "name": result.command.name,
                "args": list(result.command.args),
            }
            response_payload["reaction"] = {
                "type": "command_deferred",
                "command": result.command.name,
                "applied": False,
                "message": "Command deferred until a new app deploy is active.",
            }
            response_payload["command_defer"] = {
                "status": "deferred",
                "reason": "awaiting_new_deploy",
                "deployment_revision": self._deployment_revision,
            }
            return WebhookResponse(
                status_code=_status_for_outcome(result.outcome),
                payload=response_payload,
            )
        if result.command is not None and self._shell_mode:
            response_payload["command"] = {
                "name": result.command.name,
                "args": list(result.command.args),
            }
            if result.event is None:
                response_payload["reaction"] = {
                    "type": "workflow_dispatch_requested",
                    "applied": False,
                    "message": "Shell commands require repository context.",
                }
            else:
                self._process_shell_command(
                    event=result.event,
                    payload=payload,
                    command=result.command,
                    response_payload=response_payload,
                )
            if result.event is not None and result.event.repository is not None:
                publish_request = ReactionPublishRequest(
                    repository=result.event.repository,
                    issue_number=result.event.pull_request_number or 0,
                    command_name=result.command.name,
                    command_args=result.command.args,
                    command_raw=result.command.raw,
                    reaction=response_payload["reaction"],
                    comment_id=result.event.comment_id,
                    comment_html_url=result.event.comment_html_url,
                    installation_id=result.event.installation_id,
                )
                try:
                    reaction_publisher = self._reaction_publisher
                    if reaction_publisher is None:
                        token = self._resolve_provider_token(result.event)
                        if token is not None:
                            reaction_publisher = GitHubIssueCommentReactionPublisher(token=token)
                        else:
                            reaction_publisher = self._default_reaction_publisher
                    published_url = reaction_publisher.publish(publish_request)
                except Exception as err:  # noqa: BLE001 - reaction delivery must not fail webhook intake
                    response_payload["reaction_delivery"] = {
                        "status": "failed",
                        "reason": "publisher_error",
                        "message": str(err).strip() or "reaction publish failed",
                    }
                else:
                    if published_url:
                        response_payload["reaction_delivery"] = {
                            "status": "posted",
                            "url": published_url,
                        }
            return WebhookResponse(
                status_code=_status_for_outcome(result.outcome),
                payload=response_payload,
            )
        if result.command is not None:
            response_payload["command"] = {
                "name": result.command.name,
                "args": list(result.command.args),
            }
            recommended_label: str | None = None
            recommended_current_version: str | None = None
            if _is_release_command(result.command):
                if result.event is not None and result.event.repository is not None:
                    self._process_release_command(
                        event=result.event,
                        response_payload=response_payload,
                    )
                response_payload["reaction"] = build_release_command_reaction(response_payload)
            elif (
                result.command.name == "bump"
                and result.event is not None
                and result.event.repository is not None
                and result.event.pull_request_number is not None
            ):
                process_bump_command_release_side_effects(
                    event=result.event,
                    command=result.command,
                    response_payload=response_payload,
                    state_store=self._state_store,
                    mismatch_policy=self._config.bump_mismatch_policy,
                    resolve_tag_publisher=self._resolve_tag_publisher,
                )
            else:
                response_payload["reaction"] = _build_command_reaction(
                    result.command,
                    recommended_label=recommended_label,
                    recommended_current_version=recommended_current_version,
                    mismatch_policy=self._config.bump_mismatch_policy,
                )
            if result.event is not None and result.event.repository is not None:
                publish_request = ReactionPublishRequest(
                    repository=result.event.repository,
                    issue_number=result.event.pull_request_number or 0,
                    command_name=result.command.name,
                    command_args=result.command.args,
                    command_raw=result.command.raw,
                    reaction=response_payload["reaction"],
                    comment_id=result.event.comment_id,
                    comment_html_url=result.event.comment_html_url,
                    installation_id=result.event.installation_id,
                )
                try:
                    reaction_publisher = self._reaction_publisher
                    if reaction_publisher is None:
                        token = self._resolve_provider_token(result.event)
                        if token is not None:
                            reaction_publisher = GitHubIssueCommentPublisher(token=token)
                        else:
                            reaction_publisher = self._default_reaction_publisher
                    published_url = reaction_publisher.publish(publish_request)
                except Exception as err:  # noqa: BLE001 - reaction delivery must not fail webhook intake
                    response_payload["reaction_delivery"] = {
                        "status": "failed",
                        "reason": "publisher_error",
                        "message": str(err).strip() or "reaction publish failed",
                    }
                else:
                    if published_url:
                        response_payload["reaction_delivery"] = {
                            "status": "posted",
                            "url": published_url,
                        }
        return WebhookResponse(
            status_code=_status_for_outcome(result.outcome),
            payload=response_payload,
        )


def build_app_webhook_service(
    *,
    config: AppRuntimeConfig,
    state_store: AppStateStore | None = None,
    delivery_store: DeliveryStore | None = None,
    reaction_publisher: ReactionPublisher | None = None,
    tag_publisher: TagPublisher | None = None,
    release_publisher: ReleasePublisher | None = None,
    recommendation_runner: RecommendationRunner | None = None,
    recommendation_publisher: RecommendationPublisher | None = None,
    installation_token_provider: InstallationTokenProvider | None = None,
    workflow_dispatcher: WorkflowDispatcher | None = None,
) -> AppWebhookService:
    return AppWebhookService(
        config=config,
        state_store=state_store
        or (
            EphemeralAppStateStore()
            if config.app_mode == APP_MODE_SHELL
            and config.db_path is None
            and config.database_url is None
            else build_app_state_store(
                db_path=config.db_path,
                database_url=config.database_url,
            )
        ),
        delivery_store=delivery_store,
        reaction_publisher=reaction_publisher,
        tag_publisher=tag_publisher,
        release_publisher=release_publisher,
        recommendation_runner=recommendation_runner,
        recommendation_publisher=recommendation_publisher,
        installation_token_provider=installation_token_provider,
        workflow_dispatcher=workflow_dispatcher,
    )


def build_app_webhook_service_from_env(
    environ: Mapping[str, str] | None = None,
) -> AppWebhookService:
    return build_app_webhook_service(
        config=load_app_runtime_config(environ),
    )
