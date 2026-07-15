from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

CallModelFn = Callable[..., dict[str, str]]
AggregateChunkRecommendationsFn = Callable[..., dict[str, Any]]
ClassifiedResultFn = Callable[..., dict[str, Any]]
GetStubRecommendationFn = Callable[[bool], dict[str, Any]]
ManualReviewResultFn = Callable[..., dict[str, Any]]
ProviderModeFn = Callable[[str], str]
SemanticFallbackFn = Callable[..., dict[str, Any]]
SplitDiffIntoChunksFn = Callable[..., tuple[list[str], int]]
SplitDiffUnitsIntoChunksFn = Callable[..., tuple[list[dict[str, Any]], int, set[str], set[str]]]
WithChunkingMetadataFn = Callable[..., dict[str, Any]]


@dataclass(frozen=True, slots=True)
class RecommendationRequest:
    mode: str
    diff_text: str
    truncated: bool
    language_group: str | None
    prompt_version: str | None
    surface_area_hints: list[str] | None
    language_hints: list[str] | None
    model: str
    fallback_model: str | None
    endpoint: str
    token: str
    use_semantic_fallback: bool = True
    max_retries: int = 3
    request_timeout: int = 45
    chunking_enabled: bool = True
    chunk_max_tokens: int = 1200
    chunk_max_count: int = 24
    chunk_failure_policy: str = "MANUAL_REVIEW"
    diff_units: list[tuple[str, str]] | None = None


@dataclass(frozen=True, slots=True)
class RecommendationCallbacks:
    provider_mode_for_endpoint: ProviderModeFn
    get_stub_recommendation: GetStubRecommendationFn
    split_diff_units_into_chunks: SplitDiffUnitsIntoChunksFn
    split_diff_into_chunks: SplitDiffIntoChunksFn
    call_model: CallModelFn
    aggregate_chunk_recommendations: AggregateChunkRecommendationsFn
    classified_result: ClassifiedResultFn
    manual_review_result: ManualReviewResultFn
    semantic_fallback: SemanticFallbackFn
    with_chunking_metadata: WithChunkingMetadataFn
