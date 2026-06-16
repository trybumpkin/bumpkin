"""Compatibility facade for legacy GitHub imports.

New internal code should import from ``bumpkin.integrations.github`` directly.
This package remains as a backwards-compatible shim for external callers.
"""

from .recommendations import (
    MergeRecommendation,
    MergeRecommendationRequest,
    PipelineRecommendationRunner,
    RecommendationPublisher,
    RecommendationRunner,
)
from .releases import (
    GitHubReleasePublisher,
    NoopReleasePublisher,
    ReleasePublisher,
    ReleasePublishRequest,
    ReleasePublishResult,
)
from .tags import (
    GitHubTagPublisher,
    NoopTagPublisher,
    TagPublisher,
    TagPublishRequest,
    TagPublishResult,
)
from .types import AppEvent

__all__ = [
    "AppEvent",
    "GitHubReleasePublisher",
    "GitHubTagPublisher",
    "MergeRecommendation",
    "MergeRecommendationRequest",
    "NoopReleasePublisher",
    "NoopTagPublisher",
    "PipelineRecommendationRunner",
    "RecommendationPublisher",
    "RecommendationRunner",
    "ReleasePublishRequest",
    "ReleasePublishResult",
    "ReleasePublisher",
    "TagPublishRequest",
    "TagPublishResult",
    "TagPublisher",
]
