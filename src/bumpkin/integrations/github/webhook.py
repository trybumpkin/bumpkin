from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Self

from bumpkin.integrations.github.ingress import DeliveryStore
from bumpkin.integrations.github.persistence import AppStateStore
from bumpkin.integrations.github.reactions import ReactionPublisher
from bumpkin.integrations.github.recommendations import (
    RecommendationPublisher,
    RecommendationRunner,
)
from bumpkin.integrations.github.releases import ReleasePublisher
from bumpkin.integrations.github.runtime import AppRuntimeConfig
from bumpkin.integrations.github.tags import TagPublisher
from bumpkin.integrations.github.webhook_factory import (
    build_default_app_webhook_service as _build_default_app_webhook_service,
)
from bumpkin.integrations.github.webhook_factory import (
    build_default_app_webhook_service_from_env as _build_default_app_webhook_service_from_env,
)
from bumpkin.integrations.github.webhook_runtime import (
    InstallationTokenProvider,
    WebhookRuntime,
)
from bumpkin.integrations.github.workflows import WorkflowDispatcher

build_app_webhook_service = _build_default_app_webhook_service
build_app_webhook_service_from_env = _build_default_app_webhook_service_from_env


@dataclass(frozen=True, slots=True)
class WebhookResponse:
    status_code: int
    payload: dict[str, Any]


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
        self._state_store = state_store
        self._runtime = WebhookRuntime(
            config=config,
            state_store=state_store,
            delivery_store=delivery_store,
            reaction_publisher=reaction_publisher,
            tag_publisher=tag_publisher,
            release_publisher=release_publisher,
            recommendation_runner=recommendation_runner,
            recommendation_publisher=recommendation_publisher,
            installation_token_provider=installation_token_provider,
            workflow_dispatcher=workflow_dispatcher,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def close(self) -> None:
        self._runtime.close()

    def handle_github_webhook(
        self,
        *,
        headers: Mapping[str, object],
        raw_body: bytes,
    ) -> WebhookResponse:
        result = self._runtime.handle(headers=headers, raw_body=raw_body)
        return WebhookResponse(status_code=result.status_code, payload=result.payload)
