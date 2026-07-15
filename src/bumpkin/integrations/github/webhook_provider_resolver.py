from __future__ import annotations

from typing import Protocol

from bumpkin.integrations.github.github_auth import GitHubAppInstallationTokenProvider
from bumpkin.integrations.github.reactions import NoopReactionPublisher, ReactionPublisher
from bumpkin.integrations.github.recommendations import (
    GitHubRecommendationCommentPublisher,
    NoopRecommendationPublisher,
    RecommendationPublisher,
)
from bumpkin.integrations.github.releases import (
    GitHubReleasePublisher,
    NoopReleasePublisher,
    ReleasePublisher,
)
from bumpkin.integrations.github.runtime import AppRuntimeConfig
from bumpkin.integrations.github.tags import GitHubTagPublisher, NoopTagPublisher, TagPublisher
from bumpkin.integrations.github.types import AppEvent
from bumpkin.integrations.github.workflows import (
    GitHubWorkflowDispatcher,
    NoopWorkflowDispatcher,
    WorkflowDispatcher,
)


class InstallationTokenProviderLike(Protocol):
    def get_token(self, installation_id: int | None) -> str | None: ...


class WebhookProviderResolver:
    def __init__(
        self,
        *,
        config: AppRuntimeConfig,
        reaction_publisher: ReactionPublisher | None,
        tag_publisher: TagPublisher | None,
        release_publisher: ReleasePublisher | None,
        recommendation_publisher: RecommendationPublisher | None,
        installation_token_provider: InstallationTokenProviderLike | None,
        workflow_dispatcher: WorkflowDispatcher | None,
    ) -> None:
        self._config = config
        self._reaction_publisher = reaction_publisher
        self._tag_publisher = tag_publisher
        self._release_publisher = release_publisher
        self._recommendation_publisher = recommendation_publisher
        self._workflow_dispatcher = workflow_dispatcher
        self._installation_token_provider = _resolve_installation_token_provider(
            config,
            installation_token_provider,
        )
        self.default_reaction_publisher = NoopReactionPublisher()
        self._default_tag_publisher = NoopTagPublisher()
        self._default_release_publisher = NoopReleasePublisher()
        self._default_recommendation_publisher = NoopRecommendationPublisher()

    @property
    def configured_reaction_publisher(self) -> ReactionPublisher | None:
        return self._reaction_publisher

    def resolve_provider_token(self, event: AppEvent | None) -> str | None:
        if self._installation_token_provider is not None and event is not None:
            app_token = self._installation_token_provider.get_token(event.installation_id)
            if app_token is not None:
                return app_token
        return self._config.provider_token

    def resolve_workflow_dispatcher(self, event: AppEvent | None) -> WorkflowDispatcher:
        if self._workflow_dispatcher is not None:
            return self._workflow_dispatcher
        token = self.resolve_provider_token(event)
        return (
            GitHubWorkflowDispatcher(token=token) if token is not None else NoopWorkflowDispatcher()
        )

    def resolve_tag_publisher(self, event: AppEvent | None) -> TagPublisher:
        if self._tag_publisher is not None:
            return self._tag_publisher
        token = self.resolve_provider_token(event)
        return GitHubTagPublisher(token=token) if token is not None else self._default_tag_publisher

    def resolve_release_publisher(self, event: AppEvent | None) -> ReleasePublisher:
        if self._release_publisher is not None:
            return self._release_publisher
        token = self.resolve_provider_token(event)
        return (
            GitHubReleasePublisher(token=token)
            if token is not None
            else self._default_release_publisher
        )

    def resolve_recommendation_publisher(self, event: AppEvent | None) -> RecommendationPublisher:
        if self._recommendation_publisher is not None:
            return self._recommendation_publisher
        token = self.resolve_provider_token(event)
        return (
            GitHubRecommendationCommentPublisher(token=token)
            if token is not None
            else self._default_recommendation_publisher
        )


def _resolve_installation_token_provider(
    config: AppRuntimeConfig,
    provider: InstallationTokenProviderLike | None,
) -> InstallationTokenProviderLike | None:
    if provider is not None:
        return provider
    if config.github_app_id and config.github_app_private_key:
        return GitHubAppInstallationTokenProvider(
            app_id=config.github_app_id,
            private_key_pem=config.github_app_private_key,
        )
    return None
