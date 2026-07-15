from __future__ import annotations

from collections.abc import Mapping

from bumpkin.integrations.github.ingress import DeliveryStore, InMemoryDeliveryStore
from bumpkin.integrations.github.persistence import AppStateStore
from bumpkin.integrations.github.reactions import ReactionPublisher
from bumpkin.integrations.github.recommendations import (
    PipelineRecommendationRunner,
    RecommendationPublisher,
    RecommendationRunner,
)
from bumpkin.integrations.github.releases import ReleasePublisher
from bumpkin.integrations.github.runtime import AppRuntimeConfig
from bumpkin.integrations.github.tags import TagPublisher
from bumpkin.integrations.github.webhook_commands import _is_shell_mode as _is_shell_mode_impl
from bumpkin.integrations.github.webhook_dispatch import WebhookDispatchCoordinator
from bumpkin.integrations.github.webhook_provider_resolver import (
    InstallationTokenProviderLike,
    WebhookProviderResolver,
)
from bumpkin.integrations.github.webhook_request import WebhookRequestHandler
from bumpkin.integrations.github.webhook_runtime_effects import WebhookRuntimeEffects
from bumpkin.integrations.github.webhook_runtime_types import RuntimeWebhookResponse
from bumpkin.integrations.github.workflows import WorkflowDispatcher

InstallationTokenProvider = InstallationTokenProviderLike


class WebhookRuntime:
    def __init__(
        self,
        *,
        config: AppRuntimeConfig,
        state_store: AppStateStore,
        delivery_store: DeliveryStore | None,
        reaction_publisher: ReactionPublisher | None,
        tag_publisher: TagPublisher | None,
        release_publisher: ReleasePublisher | None,
        recommendation_runner: RecommendationRunner | None,
        recommendation_publisher: RecommendationPublisher | None,
        installation_token_provider: InstallationTokenProviderLike | None,
        workflow_dispatcher: WorkflowDispatcher | None,
    ) -> None:
        self._config = config
        self._state_store = state_store
        self._delivery_store = delivery_store or InMemoryDeliveryStore()
        self._shell_mode = _is_shell_mode(config)
        self._self_repository = (config.self_repository or "").strip().lower() or None
        self._deployment_revision = (config.deployment_revision or "").strip() or None
        self._defer_self_merge_recommendation = (
            config.defer_self_merge_recommendation_until_new_deploy
        )
        self._providers = WebhookProviderResolver(
            config=config,
            reaction_publisher=reaction_publisher,
            tag_publisher=tag_publisher,
            release_publisher=release_publisher,
            recommendation_publisher=recommendation_publisher,
            installation_token_provider=installation_token_provider,
            workflow_dispatcher=workflow_dispatcher,
        )
        self._effects = WebhookRuntimeEffects(
            config=config,
            state_store=state_store,
            recommendation_runner=recommendation_runner or PipelineRecommendationRunner(),
            providers=self._providers,
            self_repository=self._self_repository,
            deployment_revision=self._deployment_revision,
            defer_self_merge_recommendation=self._defer_self_merge_recommendation,
        )
        self._dispatch_coordinator = WebhookDispatchCoordinator(self)
        self._request_handler = WebhookRequestHandler(self)
        if not self._shell_mode:
            self._effects.replay_deferred_merge_recommendations_once()

    def close(self) -> None:
        self._state_store.close()

    def handle(
        self,
        *,
        headers: Mapping[str, object],
        raw_body: bytes,
    ) -> RuntimeWebhookResponse:
        return self._request_handler.handle(headers=headers, raw_body=raw_body)


def _is_shell_mode(config: AppRuntimeConfig) -> bool:
    return _is_shell_mode_impl(config)
