from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bumpkin.prompt_pack import PromptPackMetadata, get_prompt_metadata
from bumpkin.providers.llm_chunked import ChunkedRecommendationRunner, ChunkedRequest
from bumpkin.providers.llm_recommend_types import (
    RecommendationCallbacks,
    RecommendationRequest,
)
from bumpkin.providers.llm_single_shot import run as run_single_shot


@dataclass(frozen=True, slots=True)
class _PreparedChunks:
    payloads: list[dict[str, Any]]
    skipped: int
    files: set[str]
    omitted: set[str]


class RecommendationStrategy:
    def __init__(self, callbacks: RecommendationCallbacks) -> None:
        self._callbacks = callbacks
        self._chunked_runner = ChunkedRecommendationRunner()

    def run(
        self, request: RecommendationRequest
    ) -> tuple[dict[str, Any], str, str | None, str | None]:
        mode = request.mode.strip().lower()
        _validate_mode(mode)
        if mode == "stub":
            return self._callbacks.get_stub_recommendation(request.truncated), "stub", None, "stub"
        model_mode = self._model_mode(mode, request.endpoint)
        metadata = get_prompt_metadata(
            language_group=request.language_group,
            prompt_version=request.prompt_version,
        )
        failure_policy = _normalize_failure_policy(request.chunk_failure_policy)
        units = _normalize_units(request.diff_units)
        files_total = len({path for path, _text in units})
        if not request.chunking_enabled:
            return self._single(request, metadata, model_mode, failure_policy, files_total)
        chunks = self._prepare_chunks(request, units)
        if not chunks.payloads:
            return self._single(request, metadata, model_mode, failure_policy, files_total)
        return self._chunked(request, metadata, model_mode, failure_policy, chunks)

    def _model_mode(self, mode: str, endpoint: str) -> str:
        return (
            "openrouter"
            if mode == "openrouter"
            else self._callbacks.provider_mode_for_endpoint(endpoint)
        )

    def _prepare_chunks(
        self,
        request: RecommendationRequest,
        units: list[tuple[str, str]],
    ) -> _PreparedChunks:
        if units:
            payloads, skipped, files, omitted = self._callbacks.split_diff_units_into_chunks(
                units,
                max_chunk_tokens=request.chunk_max_tokens,
                max_chunk_count=request.chunk_max_count,
            )
            return _PreparedChunks(payloads, skipped, files, omitted)
        chunks, skipped = self._callbacks.split_diff_into_chunks(
            request.diff_text,
            max_chunk_tokens=request.chunk_max_tokens,
            max_chunk_count=request.chunk_max_count,
        )
        return _PreparedChunks(
            [{"text": chunk, "files": set()} for chunk in chunks],
            skipped,
            set(),
            set(),
        )

    def _single(
        self,
        request: RecommendationRequest,
        metadata: PromptPackMetadata,
        model_mode: str,
        failure_policy: str,
        files_total: int,
    ) -> tuple[dict[str, Any], str, str | None, str | None]:
        return run_single_shot(
            call_model_fn=self._callbacks.call_model,
            classified_result_fn=self._callbacks.classified_result,
            manual_review_result_fn=self._callbacks.manual_review_result,
            semantic_fallback_fn=self._callbacks.semantic_fallback,
            with_chunking_metadata_fn=self._callbacks.with_chunking_metadata,
            token=request.token,
            model=request.model,
            fallback_model=request.fallback_model,
            diff_text=request.diff_text,
            language_group=metadata.language_group,
            prompt_version=metadata.prompt_version,
            surface_area_hints=request.surface_area_hints,
            language_hints=request.language_hints,
            endpoint=request.endpoint,
            max_retries=request.max_retries,
            request_timeout=request.request_timeout,
            truncated=request.truncated,
            use_semantic_fallback=request.use_semantic_fallback,
            model_mode=model_mode,
            chunk_max_tokens=request.chunk_max_tokens,
            chunk_max_count=request.chunk_max_count,
            failure_policy=failure_policy,
            files_total=files_total,
            omitted_files=sorted({path for path, _text in _normalize_units(request.diff_units)})
            if request.truncated
            else [],
        )

    def _chunked(
        self,
        request: RecommendationRequest,
        metadata: PromptPackMetadata,
        model_mode: str,
        failure_policy: str,
        chunks: _PreparedChunks,
    ) -> tuple[dict[str, Any], str, str | None, str | None]:
        return self._chunked_runner.run(
            ChunkedRequest(
                call_model_fn=self._callbacks.call_model,
                aggregate_chunk_recommendations_fn=self._callbacks.aggregate_chunk_recommendations,
                classified_result_fn=self._callbacks.classified_result,
                manual_review_result_fn=self._callbacks.manual_review_result,
                semantic_fallback_fn=self._callbacks.semantic_fallback,
                with_chunking_metadata_fn=self._callbacks.with_chunking_metadata,
                token=request.token,
                model=request.model,
                fallback_model=request.fallback_model,
                diff_text=request.diff_text,
                chunk_payloads=chunks.payloads,
                skipped_chunks=chunks.skipped,
                all_chunk_files=chunks.files,
                omitted_due_to_chunk_limit=chunks.omitted,
                language_group=metadata.language_group,
                prompt_version=metadata.prompt_version,
                surface_area_hints=request.surface_area_hints,
                language_hints=request.language_hints,
                endpoint=request.endpoint,
                max_retries=request.max_retries,
                request_timeout=request.request_timeout,
                truncated=request.truncated,
                use_semantic_fallback=request.use_semantic_fallback,
                model_mode=model_mode,
                chunk_max_tokens=request.chunk_max_tokens,
                chunk_max_count=request.chunk_max_count,
                failure_policy=failure_policy,
            )
        )


def _validate_mode(mode: str) -> None:
    if mode not in {"auto", "stub", "github-models", "openrouter"}:
        raise ValueError(f"Unsupported mode: {mode!r}")


def _normalize_failure_policy(policy: str) -> str:
    normalized = policy.strip().upper()
    if normalized not in {"MANUAL_REVIEW", "PATCH"}:
        raise ValueError(f"Unsupported chunk_failure_policy: {policy!r}")
    return normalized


def _normalize_units(units: list[tuple[str, str]] | None) -> list[tuple[str, str]]:
    return [
        (str(path).strip(), text)
        for path, text in (units or [])
        if str(path or "").strip() and str(text or "").strip()
    ]
