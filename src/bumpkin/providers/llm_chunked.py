from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bumpkin.providers.llm_payloads import LLMResponseError
from bumpkin.providers.llm_recommend_types import (
    AggregateChunkRecommendationsFn,
    CallModelFn,
    ClassifiedResultFn,
    ManualReviewResultFn,
    SemanticFallbackFn,
    WithChunkingMetadataFn,
)
from bumpkin.providers.llm_single_shot import call_with_fallback
from bumpkin.providers.llm_transport import LLMUnavailableError


@dataclass(frozen=True, slots=True)
class ChunkedRequest:
    call_model_fn: CallModelFn
    aggregate_chunk_recommendations_fn: AggregateChunkRecommendationsFn
    classified_result_fn: ClassifiedResultFn
    manual_review_result_fn: ManualReviewResultFn
    semantic_fallback_fn: SemanticFallbackFn
    with_chunking_metadata_fn: WithChunkingMetadataFn
    token: str
    model: str
    fallback_model: str | None
    diff_text: str
    chunk_payloads: list[dict[str, Any]]
    skipped_chunks: int
    all_chunk_files: set[str]
    omitted_due_to_chunk_limit: set[str]
    language_group: str | None
    prompt_version: str | None
    surface_area_hints: list[str] | None
    language_hints: list[str] | None
    endpoint: str
    max_retries: int
    request_timeout: int
    truncated: bool
    use_semantic_fallback: bool
    model_mode: str
    chunk_max_tokens: int
    chunk_max_count: int
    failure_policy: str


class ChunkedRecommendationRunner:
    def run(self, request: ChunkedRequest) -> tuple[dict[str, Any], str, str | None, str | None]:
        successful, errors, models, covered, failed = self._collect(request)
        omitted = sorted(
            (request.all_chunk_files - covered) | request.omitted_due_to_chunk_limit | failed
        )
        if request.omitted_due_to_chunk_limit:
            return self._coverage_gap(request, len(successful), len(errors), omitted)
        if not errors:
            return self._successful(request, successful, models, omitted)
        return self._failed(request, successful, errors, omitted)

    def _collect(
        self,
        request: ChunkedRequest,
    ) -> tuple[list[dict[str, str]], list[str], list[str], set[str], set[str]]:
        successful: list[dict[str, str]] = []
        errors: list[str] = []
        models: list[str] = []
        covered: set[str] = set()
        failed: set[str] = set()
        for chunk in request.chunk_payloads:
            chunk_files = set(chunk["files"])
            try:
                parsed, model = call_with_fallback(
                    call_model_fn=request.call_model_fn,
                    token=request.token,
                    model=request.model,
                    fallback_model=request.fallback_model,
                    diff_text=str(chunk["text"]),
                    language_group=request.language_group,
                    prompt_version=request.prompt_version,
                    surface_area_hints=request.surface_area_hints,
                    language_hints=request.language_hints,
                    endpoint=request.endpoint,
                    max_retries=request.max_retries,
                    request_timeout=request.request_timeout,
                )
            except (LLMUnavailableError, LLMResponseError) as err:
                errors.append(str(err))
                failed.update(chunk_files)
            else:
                successful.append(parsed)
                models.append(model)
                covered.update(chunk_files)
        return successful, errors, models, covered, failed

    def _coverage_gap(
        self,
        request: ChunkedRequest,
        succeeded: int,
        failed: int,
        omitted: list[str],
    ) -> tuple[dict[str, Any], str, str | None, str | None]:
        result = request.manual_review_result_fn(
            reasoning="Chunked model analysis omitted one or more files because chunk limits were reached. Please review manually."
        )
        return (
            self._metadata(
                request, result, len(request.chunk_payloads), succeeded, failed, omitted
            ),
            request.model_mode,
            "chunk_limit_coverage_gap",
            "mixed",
        )

    def _successful(
        self,
        request: ChunkedRequest,
        successful: list[dict[str, str]],
        models: list[str],
        omitted: list[str],
    ) -> tuple[dict[str, Any], str, str | None, str | None]:
        result = request.aggregate_chunk_recommendations_fn(successful, truncated=request.truncated)
        used_model = models[0] if len(set(models)) == 1 else "mixed"
        return (
            self._metadata(request, result, len(successful), len(successful), 0, omitted),
            request.model_mode,
            None,
            used_model,
        )

    def _failed(
        self,
        request: ChunkedRequest,
        successful: list[dict[str, str]],
        errors: list[str],
        omitted: list[str],
    ) -> tuple[dict[str, Any], str, str | None, str | None]:
        reason = "; ".join(errors[:2])
        if not successful:
            return self._all_failed(request, reason, len(errors), omitted)
        reasoning = (
            f"Chunked model analysis succeeded for {len(successful)}/{len(request.chunk_payloads)} chunk(s), "
            f"but {len(errors)} chunk(s) failed; reliable aggregate classification is unavailable."
        )
        if request.truncated:
            reasoning += " Diff was truncated before chunking."
        result = (
            request.classified_result_fn(
                label="PATCH",
                confidence="low",
                reasoning=reasoning,
                changelog="fix: conservative patch bump due to partial chunk failures",
            )
            if request.failure_policy == "PATCH"
            else request.manual_review_result_fn(reasoning=reasoning)
        )
        return (
            self._metadata(
                request, result, len(request.chunk_payloads), len(successful), len(errors), omitted
            ),
            request.model_mode,
            reason,
            "mixed",
        )

    def _all_failed(
        self,
        request: ChunkedRequest,
        reason: str,
        failed: int,
        omitted: list[str],
    ) -> tuple[dict[str, Any], str, str | None, str | None]:
        if request.use_semantic_fallback:
            result = request.semantic_fallback_fn(
                diff_text=request.diff_text,
                surface_area_hints=request.surface_area_hints,
                truncated=request.truncated,
            )
            return (
                self._metadata(request, result, len(request.chunk_payloads), 0, failed, omitted),
                "fallback-heuristic",
                reason,
                "semantic-fallback",
            )
        result = request.manual_review_result_fn(
            reasoning="Chunked model analysis failed for all chunks. Please classify this PR manually."
        )
        return (
            self._metadata(request, result, len(request.chunk_payloads), 0, failed, omitted),
            request.model_mode,
            reason,
            None,
        )

    def _metadata(
        self,
        request: ChunkedRequest,
        result: dict[str, Any],
        chunk_count: int,
        succeeded: int,
        failed: int,
        omitted: list[str],
    ) -> dict[str, Any]:
        return request.with_chunking_metadata_fn(
            result,
            enabled=True,
            chunk_count=chunk_count,
            succeeded=succeeded,
            failed=failed,
            skipped=request.skipped_chunks,
            max_chunk_tokens=request.chunk_max_tokens,
            max_chunk_count=request.chunk_max_count,
            failure_policy=request.failure_policy,
            files_total=len(request.all_chunk_files),
            omitted_files=omitted,
        )
