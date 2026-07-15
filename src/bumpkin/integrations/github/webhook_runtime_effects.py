from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from bumpkin.integrations.github.persistence import AppStateStore
from bumpkin.integrations.github.recommendations import RecommendationRunner
from bumpkin.integrations.github.runtime import AppRuntimeConfig
from bumpkin.integrations.github.types import AppEvent, SlashCommand
from bumpkin.integrations.github.webhook_provider_resolver import WebhookProviderResolver
from bumpkin.integrations.github.webhook_release_flow import (
    dispatch_release_workflow_command,
)
from bumpkin.integrations.github.webhook_release_flow import (
    process_release_command as _process_release_command_impl,
)
from bumpkin.integrations.github.webhook_service_deferred import (
    replay_deferred_merge_recommendations_once,
)
from bumpkin.integrations.github.webhook_service_merge import process_merge_recommendation


class WebhookRuntimeEffects:
    def __init__(
        self,
        *,
        config: AppRuntimeConfig,
        state_store: AppStateStore,
        recommendation_runner: RecommendationRunner,
        providers: WebhookProviderResolver,
        self_repository: str | None,
        deployment_revision: str | None,
        defer_self_merge_recommendation: bool,
    ) -> None:
        self._config = config
        self._state_store = state_store
        self._recommendation_runner = recommendation_runner
        self._providers = providers
        self._self_repository = self_repository
        self._deployment_revision = deployment_revision
        self._defer_self_merge_recommendation = defer_self_merge_recommendation

    def process_merge_recommendation(
        self,
        *,
        event: AppEvent,
        payload: Mapping[str, object],
        response_payload: dict[str, Any] | None,
    ) -> None:
        process_merge_recommendation(
            event=event,
            payload=payload,
            response_payload=response_payload,
            state_store=self._state_store,
            recommendation_runner=self._recommendation_runner,
            resolve_provider_token=self._providers.resolve_provider_token,
            resolve_recommendation_publisher=self._providers.resolve_recommendation_publisher,
        )

    def process_shell_command(
        self,
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
            dispatcher=self._providers.resolve_workflow_dispatcher(event),
        )

    def process_release_command(self, event: AppEvent, response_payload: dict[str, Any]) -> None:
        _process_release_command_impl(
            event=event,
            response_payload=response_payload,
            state_store=self._state_store,
            resolve_tag_publisher=self._providers.resolve_tag_publisher,
            resolve_release_publisher=self._providers.resolve_release_publisher,
        )

    def replay_deferred_merge_recommendations_once(self) -> None:
        replay_deferred_merge_recommendations_once(
            defer_self_merge_recommendation=self._defer_self_merge_recommendation,
            self_repository=self._self_repository,
            deployment_revision=self._deployment_revision,
            state_store=self._state_store,
            process_merge_recommendation_fn=lambda event, payload, response_payload: (
                self.process_merge_recommendation(
                    event=event,
                    payload=payload,
                    response_payload=response_payload,
                )
            ),
        )
