from __future__ import annotations

from typing import Any

from bumpkin.providers.llm_payloads import LLMResponseError
from bumpkin.providers.llm_recommend_types import (
    CallModelFn,
    ClassifiedResultFn,
    ManualReviewResultFn,
    SemanticFallbackFn,
    WithChunkingMetadataFn,
)
from bumpkin.providers.llm_transport import LLMUnavailableError


def call_with_fallback(
    *,
    call_model_fn: CallModelFn,
    token: str,
    model: str,
    fallback_model: str | None,
    diff_text: str,
    language_group: str | None,
    prompt_version: str | None,
    surface_area_hints: list[str] | None,
    language_hints: list[str] | None,
    endpoint: str,
    max_retries: int,
    request_timeout: int,
) -> tuple[dict[str, str], str]:
    try:
        return _call_model(
            call_model_fn=call_model_fn,
            token=token,
            model=model,
            diff_text=diff_text,
            language_group=language_group,
            prompt_version=prompt_version,
            surface_area_hints=surface_area_hints,
            language_hints=language_hints,
            endpoint=endpoint,
            max_retries=max_retries,
            request_timeout=request_timeout,
        ), model
    except LLMUnavailableError as primary_err:
        if fallback_model and fallback_model.strip() and fallback_model != model:
            try:
                return _call_model(
                    call_model_fn=call_model_fn,
                    token=token,
                    model=fallback_model,
                    diff_text=diff_text,
                    language_group=language_group,
                    prompt_version=prompt_version,
                    surface_area_hints=surface_area_hints,
                    language_hints=language_hints,
                    endpoint=endpoint,
                    max_retries=max_retries,
                    request_timeout=request_timeout,
                ), fallback_model
            except (LLMUnavailableError, LLMResponseError) as fallback_err:
                raise LLMUnavailableError(
                    f"Primary model failed: {primary_err}. Fallback model failed: {fallback_err}."
                ) from fallback_err
        raise LLMUnavailableError(str(primary_err)) from primary_err


def _call_model(*, call_model_fn: CallModelFn, **kwargs: Any) -> dict[str, str]:
    return call_model_fn(**kwargs)


def run(
    *,
    call_model_fn: CallModelFn,
    classified_result_fn: ClassifiedResultFn,
    manual_review_result_fn: ManualReviewResultFn,
    semantic_fallback_fn: SemanticFallbackFn,
    with_chunking_metadata_fn: WithChunkingMetadataFn,
    token: str,
    model: str,
    fallback_model: str | None,
    diff_text: str,
    language_group: str | None,
    prompt_version: str | None,
    surface_area_hints: list[str] | None,
    language_hints: list[str] | None,
    endpoint: str,
    max_retries: int,
    request_timeout: int,
    truncated: bool,
    use_semantic_fallback: bool,
    model_mode: str,
    chunk_max_tokens: int,
    chunk_max_count: int,
    failure_policy: str,
    files_total: int,
    omitted_files: list[str] | None,
) -> tuple[dict[str, Any], str, str | None, str | None]:
    try:
        parsed, used_model = call_with_fallback(
            call_model_fn=call_model_fn,
            token=token,
            model=model,
            fallback_model=fallback_model,
            diff_text=diff_text,
            language_group=language_group,
            prompt_version=prompt_version,
            surface_area_hints=surface_area_hints,
            language_hints=language_hints,
            endpoint=endpoint,
            max_retries=max_retries,
            request_timeout=request_timeout,
        )
        if truncated:
            parsed["reasoning"] += " (diff truncated; review manually)"
        result = classified_result_fn(
            label=parsed["label"],
            confidence=parsed["confidence"],
            reasoning=parsed["reasoning"],
            changelog=parsed["changelog"],
        )
        return (
            _with_metadata(
                result,
                with_chunking_metadata_fn=with_chunking_metadata_fn,
                files_total=files_total,
                omitted_files=omitted_files,
                chunk_max_tokens=chunk_max_tokens,
                chunk_max_count=chunk_max_count,
                failure_policy=failure_policy,
                succeeded=1,
            ),
            model_mode,
            None,
            used_model,
        )
    except (LLMUnavailableError, LLMResponseError) as err:
        if use_semantic_fallback:
            fallback = semantic_fallback_fn(
                diff_text=diff_text,
                surface_area_hints=surface_area_hints,
                truncated=truncated,
            )
            return (
                _with_metadata(
                    fallback,
                    with_chunking_metadata_fn=with_chunking_metadata_fn,
                    files_total=files_total,
                    omitted_files=omitted_files,
                    chunk_max_tokens=chunk_max_tokens,
                    chunk_max_count=chunk_max_count,
                    failure_policy=failure_policy,
                    succeeded=0,
                ),
                "fallback-heuristic",
                str(err),
                "semantic-fallback",
            )
        reason = (
            "Automatic model analysis was unavailable. Please classify this PR manually."
            if isinstance(err, LLMUnavailableError)
            else "Automatic model analysis returned an invalid response. Please classify this PR manually."
        )
        manual = manual_review_result_fn(reasoning=reason)
        return (
            _with_metadata(
                manual,
                with_chunking_metadata_fn=with_chunking_metadata_fn,
                files_total=files_total,
                omitted_files=omitted_files,
                chunk_max_tokens=chunk_max_tokens,
                chunk_max_count=chunk_max_count,
                failure_policy=failure_policy,
                succeeded=0,
            ),
            model_mode,
            str(err),
            None,
        )


def _with_metadata(
    result: dict[str, Any],
    *,
    with_chunking_metadata_fn: WithChunkingMetadataFn,
    files_total: int,
    omitted_files: list[str] | None,
    chunk_max_tokens: int,
    chunk_max_count: int,
    failure_policy: str,
    succeeded: int,
) -> dict[str, Any]:
    return with_chunking_metadata_fn(
        result,
        enabled=False,
        chunk_count=1,
        succeeded=succeeded,
        failed=0,
        skipped=0,
        max_chunk_tokens=chunk_max_tokens,
        max_chunk_count=chunk_max_count,
        failure_policy=failure_policy,
        files_total=files_total,
        omitted_files=omitted_files,
    )
