from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, TypeVar

from bumpkin.integrations.github.ingress import DeliveryStore
from bumpkin.integrations.github.persistence import (
    AppStateStore,
    EphemeralAppStateStore,
    build_app_state_store,
)
from bumpkin.integrations.github.reactions import ReactionPublisher
from bumpkin.integrations.github.recommendations import (
    RecommendationPublisher,
    RecommendationRunner,
)
from bumpkin.integrations.github.releases import ReleasePublisher
from bumpkin.integrations.github.runtime import (
    APP_MODE_SHELL,
    AppRuntimeConfig,
    load_app_runtime_config,
)
from bumpkin.integrations.github.tags import TagPublisher
from bumpkin.integrations.github.workflows import WorkflowDispatcher

ServiceT_co = TypeVar("ServiceT_co", covariant=True)


class InstallationTokenProviderLike(Protocol):
    def get_token(self, installation_id: int | None) -> str | None: ...


class WebhookServiceFactory(Protocol[ServiceT_co]):
    def __call__(
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
        installation_token_provider: InstallationTokenProviderLike | None = None,
        workflow_dispatcher: WorkflowDispatcher | None = None,
    ) -> ServiceT_co: ...


def build_webhook_state_store(config: AppRuntimeConfig) -> AppStateStore:
    if config.app_mode == APP_MODE_SHELL and config.db_path is None and config.database_url is None:
        return EphemeralAppStateStore()
    return build_app_state_store(
        db_path=config.db_path,
        database_url=config.database_url,
    )


def build_app_webhook_service(
    *,
    service_factory: WebhookServiceFactory[ServiceT_co],
    config: AppRuntimeConfig,
    state_store: AppStateStore | None = None,
    delivery_store: DeliveryStore | None = None,
    reaction_publisher: ReactionPublisher | None = None,
    tag_publisher: TagPublisher | None = None,
    release_publisher: ReleasePublisher | None = None,
    recommendation_runner: RecommendationRunner | None = None,
    recommendation_publisher: RecommendationPublisher | None = None,
    installation_token_provider: InstallationTokenProviderLike | None = None,
    workflow_dispatcher: WorkflowDispatcher | None = None,
) -> ServiceT_co:
    return service_factory(
        config=config,
        state_store=state_store or build_webhook_state_store(config),
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
    *,
    service_factory: WebhookServiceFactory[ServiceT_co],
    environ: Mapping[str, str] | None = None,
) -> ServiceT_co:
    return build_app_webhook_service(
        service_factory=service_factory,
        config=load_app_runtime_config(environ),
    )
