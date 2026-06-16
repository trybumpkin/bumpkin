"""Compatibility facade for legacy GitHub release imports."""

from bumpkin.integrations.github.releases import (
    GitHubReleasePublisher,
    NoopReleasePublisher,
    ReleasePublisher,
    ReleasePublishRequest,
    ReleasePublishResult,
)

__all__ = [
    "GitHubReleasePublisher",
    "NoopReleasePublisher",
    "ReleasePublishRequest",
    "ReleasePublishResult",
    "ReleasePublisher",
]
