from __future__ import annotations

from collections.abc import Callable
from typing import Any

from bumpkin.prompt_pack import get_prompt_metadata
from bumpkin.providers.llm_payloads import LLMResponseError
from bumpkin.providers.llm_transport import LLMUnavailableError

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


def call_chunk_with_fallback(
    *,
    call_model_fn: CallModelFn,
    token: str,
    model: str,
    fallback_model: str | None,
    chunk_diff: str,
    language_group: str | None,
    prompt_version: str | None,
    surface_area_hints: list[str] | None,
    language_hints: list[str] | None,
    endpoint: str,
    max_retries: int,
    request_timeout: int,
) -> tuple[dict[str, str], str]:
    try:
        recommendation = call_model_fn(
            token=token,
            model=model,
            diff_text=chunk_diff,
            language_group=language_group,
            prompt_version=prompt_version,
            surface_area_hints=surface_area_hints,
            language_hints=language_hints,
            endpoint=endpoint,
            max_retries=max_retries,
            request_timeout=request_timeout,
        )
        return recommendation, model
    except LLMUnavailableError as primary_err:
        if fallback_model and fallback_model.strip() and fallback_model != model:
            try:
                recommendation = call_model_fn(
                    token=token,
                    model=fallback_model,
                    diff_text=chunk_diff,
                    language_group=language_group,
                    prompt_version=prompt_version,
                    surface_area_hints=surface_area_hints,
                    language_hints=language_hints,
                    endpoint=endpoint,
                    max_retries=max_retries,
                    request_timeout=request_timeout,
                )
                return recommendation, fallback_model
            except (LLMUnavailableError, LLMResponseError) as fallback_err:
                raise LLMUnavailableError(
                    f"Primary model failed: {primary_err}. Fallback model failed: {fallback_err}."
                ) from fallback_err
        raise LLMUnavailableError(str(primary_err)) from primary_err


def run_single_shot_recommendation(
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
        parsed, used_model = call_chunk_with_fallback(
            call_model_fn=call_model_fn,
            token=token,
            model=model,
            fallback_model=fallback_model,
            chunk_diff=diff_text,
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
        result = with_chunking_metadata_fn(
            result,
            enabled=False,
            chunk_count=1,
            succeeded=1,
            failed=0,
            skipped=0,
            max_chunk_tokens=chunk_max_tokens,
            max_chunk_count=chunk_max_count,
            failure_policy=failure_policy,
            files_total=files_total,
            omitted_files=omitted_files,
        )
        return result, model_mode, None, used_model
    except LLMUnavailableError as err:
        if use_semantic_fallback:
            fallback_result = semantic_fallback_fn(
                diff_text=diff_text,
                surface_area_hints=surface_area_hints,
                truncated=truncated,
            )
            fallback_result = with_chunking_metadata_fn(
                fallback_result,
                enabled=False,
                chunk_count=1,
                succeeded=0,
                failed=1,
                skipped=0,
                max_chunk_tokens=chunk_max_tokens,
                max_chunk_count=chunk_max_count,
                failure_policy=failure_policy,
                files_total=files_total,
                omitted_files=omitted_files,
            )
            return (
                fallback_result,
                "fallback-heuristic",
                str(err),
                "semantic-fallback",
            )
        manual = manual_review_result_fn(
            reasoning="Automatic model analysis was unavailable. Please classify this PR manually."
        )
        manual = with_chunking_metadata_fn(
            manual,
            enabled=False,
            chunk_count=1,
            succeeded=0,
            failed=1,
            skipped=0,
            max_chunk_tokens=chunk_max_tokens,
            max_chunk_count=chunk_max_count,
            failure_policy=failure_policy,
            files_total=files_total,
            omitted_files=omitted_files,
        )
        return manual, model_mode, str(err), None
    except LLMResponseError as err:
        if use_semantic_fallback:
            fallback_result = semantic_fallback_fn(
                diff_text=diff_text,
                surface_area_hints=surface_area_hints,
                truncated=truncated,
            )
            fallback_result = with_chunking_metadata_fn(
                fallback_result,
                enabled=False,
                chunk_count=1,
                succeeded=0,
                failed=1,
                skipped=0,
                max_chunk_tokens=chunk_max_tokens,
                max_chunk_count=chunk_max_count,
                failure_policy=failure_policy,
                files_total=files_total,
                omitted_files=omitted_files,
            )
            return (
                fallback_result,
                "fallback-heuristic",
                str(err),
                "semantic-fallback",
            )
        manual = manual_review_result_fn(
            reasoning=(
                "Automatic model analysis returned an invalid response. "
                "Please classify this PR manually."
            )
        )
        manual = with_chunking_metadata_fn(
            manual,
            enabled=False,
            chunk_count=1,
            succeeded=0,
            failed=1,
            skipped=0,
            max_chunk_tokens=chunk_max_tokens,
            max_chunk_count=chunk_max_count,
            failure_policy=failure_policy,
            files_total=files_total,
            omitted_files=omitted_files,
        )
        return manual, model_mode, str(err), None


def run_chunked_recommendation(
    *,
    call_model_fn: CallModelFn,
    aggregate_chunk_recommendations_fn: AggregateChunkRecommendationsFn,
    classified_result_fn: ClassifiedResultFn,
    manual_review_result_fn: ManualReviewResultFn,
    semantic_fallback_fn: SemanticFallbackFn,
    with_chunking_metadata_fn: WithChunkingMetadataFn,
    token: str,
    model: str,
    fallback_model: str | None,
    diff_text: str,
    chunk_payloads: list[dict[str, Any]],
    skipped_chunks: int,
    all_chunk_files: set[str],
    omitted_due_to_chunk_limit: set[str],
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
) -> tuple[dict[str, Any], str, str | None, str | None]:
    successful: list[dict[str, str]] = []
    chunk_errors: list[str] = []
    models_used: list[str] = []
    covered_files: set[str] = set()
    failed_files: set[str] = set()
    for chunk in chunk_payloads:
        chunk_text = str(chunk["text"])
        chunk_files = set(chunk["files"])
        try:
            parsed, used_model = call_chunk_with_fallback(
                call_model_fn=call_model_fn,
                token=token,
                model=model,
                fallback_model=fallback_model,
                chunk_diff=chunk_text,
                language_group=language_group,
                prompt_version=prompt_version,
                surface_area_hints=surface_area_hints,
                language_hints=language_hints,
                endpoint=endpoint,
                max_retries=max_retries,
                request_timeout=request_timeout,
            )
            successful.append(parsed)
            models_used.append(used_model)
            covered_files.update(chunk_files)
        except (LLMUnavailableError, LLMResponseError) as err:
            chunk_errors.append(str(err))
            failed_files.update(chunk_files)

    chunk_count = len(chunk_payloads)
    success_count = len(successful)
    failed_count = len(chunk_errors)
    omitted_files_set = (
        (all_chunk_files - covered_files) | omitted_due_to_chunk_limit | failed_files
    )
    omitted_files = sorted(omitted_files_set)
    files_total_for_metadata = len(all_chunk_files)
    if omitted_due_to_chunk_limit:
        manual = manual_review_result_fn(
            reasoning=(
                "Chunked model analysis omitted one or more files because chunk limits were reached. "
                "Please review manually."
            )
        )
        manual = with_chunking_metadata_fn(
            manual,
            enabled=True,
            chunk_count=chunk_count,
            succeeded=success_count,
            failed=failed_count,
            skipped=skipped_chunks,
            max_chunk_tokens=chunk_max_tokens,
            max_chunk_count=chunk_max_count,
            failure_policy=failure_policy,
            files_total=files_total_for_metadata,
            omitted_files=omitted_files,
        )
        return manual, model_mode, "chunk_limit_coverage_gap", "mixed"

    if failed_count == 0:
        aggregated = aggregate_chunk_recommendations_fn(
            successful,
            truncated=truncated,
        )
        aggregated = with_chunking_metadata_fn(
            aggregated,
            enabled=True,
            chunk_count=chunk_count,
            succeeded=success_count,
            failed=failed_count,
            skipped=skipped_chunks,
            max_chunk_tokens=chunk_max_tokens,
            max_chunk_count=chunk_max_count,
            failure_policy=failure_policy,
            files_total=files_total_for_metadata,
            omitted_files=omitted_files,
        )
        model_used = models_used[0] if len(set(models_used)) == 1 else "mixed"
        return aggregated, model_mode, None, model_used

    fallback_reason = "; ".join(chunk_errors[:2])
    if success_count == 0:
        if use_semantic_fallback:
            fallback_result = semantic_fallback_fn(
                diff_text=diff_text,
                surface_area_hints=surface_area_hints,
                truncated=truncated,
            )
            fallback_result = with_chunking_metadata_fn(
                fallback_result,
                enabled=True,
                chunk_count=chunk_count,
                succeeded=success_count,
                failed=failed_count,
                skipped=skipped_chunks,
                max_chunk_tokens=chunk_max_tokens,
                max_chunk_count=chunk_max_count,
                failure_policy=failure_policy,
                files_total=files_total_for_metadata,
                omitted_files=omitted_files,
            )
            return (
                fallback_result,
                "fallback-heuristic",
                fallback_reason,
                "semantic-fallback",
            )
        manual = manual_review_result_fn(
            reasoning="Chunked model analysis failed for all chunks. Please classify this PR manually."
        )
        manual = with_chunking_metadata_fn(
            manual,
            enabled=True,
            chunk_count=chunk_count,
            succeeded=success_count,
            failed=failed_count,
            skipped=skipped_chunks,
            max_chunk_tokens=chunk_max_tokens,
            max_chunk_count=chunk_max_count,
            failure_policy=failure_policy,
            files_total=files_total_for_metadata,
            omitted_files=omitted_files,
        )
        return manual, model_mode, fallback_reason, None

    reasoning = (
        f"Chunked model analysis succeeded for {success_count}/{chunk_count} chunk(s), "
        f"but {failed_count} chunk(s) failed; reliable aggregate classification is unavailable."
    )
    if truncated:
        reasoning += " Diff was truncated before chunking."
    if failure_policy == "PATCH":
        partial = classified_result_fn(
            label="PATCH",
            confidence="low",
            reasoning=reasoning,
            changelog="fix: conservative patch bump due to partial chunk failures",
        )
    else:
        partial = manual_review_result_fn(reasoning=reasoning)

    partial = with_chunking_metadata_fn(
        partial,
        enabled=True,
        chunk_count=chunk_count,
        succeeded=success_count,
        failed=failed_count,
        skipped=skipped_chunks,
        max_chunk_tokens=chunk_max_tokens,
        max_chunk_count=chunk_max_count,
        failure_policy=failure_policy,
        files_total=files_total_for_metadata,
        omitted_files=omitted_files,
    )
    return partial, model_mode, fallback_reason, "mixed"


def get_recommendation(
    *,
    provider_mode_for_endpoint_fn: ProviderModeFn,
    get_stub_recommendation_fn: GetStubRecommendationFn,
    split_diff_units_into_chunks_fn: SplitDiffUnitsIntoChunksFn,
    split_diff_into_chunks_fn: SplitDiffIntoChunksFn,
    call_model_fn: CallModelFn,
    aggregate_chunk_recommendations_fn: AggregateChunkRecommendationsFn,
    classified_result_fn: ClassifiedResultFn,
    manual_review_result_fn: ManualReviewResultFn,
    semantic_fallback_fn: SemanticFallbackFn,
    with_chunking_metadata_fn: WithChunkingMetadataFn,
    mode: str,
    diff_text: str,
    truncated: bool,
    language_group: str | None,
    prompt_version: str | None,
    surface_area_hints: list[str] | None,
    language_hints: list[str] | None,
    model: str,
    fallback_model: str | None,
    endpoint: str,
    token: str,
    use_semantic_fallback: bool = True,
    max_retries: int = 3,
    request_timeout: int = 45,
    chunking_enabled: bool = True,
    chunk_max_tokens: int = 1200,
    chunk_max_count: int = 24,
    chunk_failure_policy: str = "MANUAL_REVIEW",
    diff_units: list[tuple[str, str]] | None = None,
) -> tuple[dict[str, Any], str, str | None, str | None]:
    normalized_mode = mode.strip().lower()
    if normalized_mode not in {"auto", "stub", "github-models", "openrouter"}:
        raise ValueError(f"Unsupported mode: {mode!r}")

    if normalized_mode == "stub":
        return get_stub_recommendation_fn(truncated), "stub", None, "stub"

    model_mode = (
        "openrouter" if normalized_mode == "openrouter" else provider_mode_for_endpoint_fn(endpoint)
    )
    prompt_metadata = get_prompt_metadata(
        language_group=language_group,
        prompt_version=prompt_version,
    )

    normalized_chunk_failure_policy = chunk_failure_policy.strip().upper()
    if normalized_chunk_failure_policy not in {"MANUAL_REVIEW", "PATCH"}:
        raise ValueError(f"Unsupported chunk_failure_policy: {chunk_failure_policy!r}")

    normalized_units = [
        (str(path).strip(), text)
        for path, text in (diff_units or [])
        if str(path or "").strip() and str(text or "").strip()
    ]
    known_files = sorted({path for path, _ in normalized_units})
    files_total = len(known_files)
    single_shot_omitted_files = known_files if truncated else []

    if not chunking_enabled:
        return run_single_shot_recommendation(
            call_model_fn=call_model_fn,
            classified_result_fn=classified_result_fn,
            manual_review_result_fn=manual_review_result_fn,
            semantic_fallback_fn=semantic_fallback_fn,
            with_chunking_metadata_fn=with_chunking_metadata_fn,
            token=token,
            model=model,
            fallback_model=fallback_model,
            diff_text=diff_text,
            language_group=prompt_metadata.language_group,
            prompt_version=prompt_metadata.prompt_version,
            surface_area_hints=surface_area_hints,
            language_hints=language_hints,
            endpoint=endpoint,
            max_retries=max_retries,
            request_timeout=request_timeout,
            truncated=truncated,
            use_semantic_fallback=use_semantic_fallback,
            model_mode=model_mode,
            chunk_max_tokens=chunk_max_tokens,
            chunk_max_count=chunk_max_count,
            failure_policy=normalized_chunk_failure_policy,
            files_total=files_total,
            omitted_files=single_shot_omitted_files,
        )

    chunk_payloads: list[dict[str, Any]]
    skipped_chunks: int
    omitted_due_to_chunk_limit: set[str]
    all_chunk_files: set[str]
    if normalized_units:
        chunk_payloads, skipped_chunks, all_chunk_files, omitted_due_to_chunk_limit = (
            split_diff_units_into_chunks_fn(
                normalized_units,
                max_chunk_tokens=chunk_max_tokens,
                max_chunk_count=chunk_max_count,
            )
        )
    else:
        chunks, skipped_chunks = split_diff_into_chunks_fn(
            diff_text,
            max_chunk_tokens=chunk_max_tokens,
            max_chunk_count=chunk_max_count,
        )
        chunk_payloads = [{"text": chunk, "files": set()} for chunk in chunks]
        all_chunk_files = set()
        omitted_due_to_chunk_limit = set()

    if not chunk_payloads:
        return run_single_shot_recommendation(
            call_model_fn=call_model_fn,
            classified_result_fn=classified_result_fn,
            manual_review_result_fn=manual_review_result_fn,
            semantic_fallback_fn=semantic_fallback_fn,
            with_chunking_metadata_fn=with_chunking_metadata_fn,
            token=token,
            model=model,
            fallback_model=fallback_model,
            diff_text=diff_text,
            language_group=prompt_metadata.language_group,
            prompt_version=prompt_metadata.prompt_version,
            surface_area_hints=surface_area_hints,
            language_hints=language_hints,
            endpoint=endpoint,
            max_retries=max_retries,
            request_timeout=request_timeout,
            truncated=truncated,
            use_semantic_fallback=use_semantic_fallback,
            model_mode=model_mode,
            chunk_max_tokens=chunk_max_tokens,
            chunk_max_count=chunk_max_count,
            failure_policy=normalized_chunk_failure_policy,
            files_total=files_total,
            omitted_files=single_shot_omitted_files,
        )

    return run_chunked_recommendation(
        call_model_fn=call_model_fn,
        aggregate_chunk_recommendations_fn=aggregate_chunk_recommendations_fn,
        classified_result_fn=classified_result_fn,
        manual_review_result_fn=manual_review_result_fn,
        semantic_fallback_fn=semantic_fallback_fn,
        with_chunking_metadata_fn=with_chunking_metadata_fn,
        token=token,
        model=model,
        fallback_model=fallback_model,
        diff_text=diff_text,
        chunk_payloads=chunk_payloads,
        skipped_chunks=skipped_chunks,
        all_chunk_files=all_chunk_files,
        omitted_due_to_chunk_limit=omitted_due_to_chunk_limit,
        language_group=prompt_metadata.language_group,
        prompt_version=prompt_metadata.prompt_version,
        surface_area_hints=surface_area_hints,
        language_hints=language_hints,
        endpoint=endpoint,
        max_retries=max_retries,
        request_timeout=request_timeout,
        truncated=truncated,
        use_semantic_fallback=use_semantic_fallback,
        model_mode=model_mode,
        chunk_max_tokens=chunk_max_tokens,
        chunk_max_count=chunk_max_count,
        failure_policy=normalized_chunk_failure_policy,
    )
