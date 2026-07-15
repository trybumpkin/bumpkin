from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from bumpkin.integrations.github.reactions import ReactionPublisher
from bumpkin.integrations.github.recommendations import RecommendationPublisher
from bumpkin.integrations.github.tags import TagPublisher
from bumpkin.integrations.github.types import AppEvent, SlashCommand

ResolveProviderTokenFn = Callable[[AppEvent | None], str | None]
ResolveRecommendationPublisherFn = Callable[[AppEvent | None], RecommendationPublisher]
ReactionPublisherFactory = Callable[[str], ReactionPublisher]
ResolveTagPublisherFn = Callable[[AppEvent | None], TagPublisher]
ProcessMergeRecommendationFn = Callable[
    [AppEvent, Mapping[str, object], dict[str, Any] | None], None
]
ProcessReleaseCommandFn = Callable[[AppEvent, dict[str, Any]], None]
ProcessShellCommandFn = Callable[
    [AppEvent, Mapping[str, object], SlashCommand, dict[str, Any]], None
]
