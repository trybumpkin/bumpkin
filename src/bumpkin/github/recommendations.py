"""Compatibility facade for legacy GitHub recommendation imports."""

from bumpkin.integrations.github.recommendations import (
    GitHubRecommendationCommentPublisher,
    MergeRecommendation,
    MergeRecommendationRequest,
    NoopRecommendationPublisher,
    PipelineRecommendationRunner,
    RecommendationPublisher,
    RecommendationRunner,
)

__all__ = [
    "GitHubRecommendationCommentPublisher",
    "MergeRecommendation",
    "MergeRecommendationRequest",
    "NoopRecommendationPublisher",
    "PipelineRecommendationRunner",
    "RecommendationPublisher",
    "RecommendationRunner",
]
