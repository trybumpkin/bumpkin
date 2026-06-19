from __future__ import annotations

from typing import Any

from bumpkin.prompt_pack import build_messages as build_prompt_messages
from bumpkin.providers.chunking import (
    aggregate_chunk_recommendations as _aggregate_chunk_recommendations_impl,
)
from bumpkin.providers.chunking import (
    split_diff_into_chunks as _split_diff_into_chunks_impl,
)
from bumpkin.providers.chunking import (
    split_diff_units_into_chunks as _split_diff_units_into_chunks_impl,
)
from bumpkin.providers.chunking import (
    with_chunking_metadata as _with_chunking_metadata_impl,
)
from bumpkin.providers.llm_payloads import (
    AGGREGATE_CHANGELOG,
    VALID_LABELS,
)
from bumpkin.providers.llm_payloads import (
    LLMResponseError as _LLMResponseError_impl,
)
from bumpkin.providers.llm_payloads import (
    coerce_recommendation_payload as _coerce_recommendation_payload_impl,
)
from bumpkin.providers.llm_payloads import (
    extract_content as _extract_content_impl,
)
from bumpkin.providers.llm_payloads import (
    extract_json_payload as _extract_json_payload_impl,
)
from bumpkin.providers.llm_payloads import (
    normalize_confidence as _normalize_confidence_impl,
)
from bumpkin.providers.llm_payloads import (
    normalize_label as _normalize_label_impl,
)
from bumpkin.providers.llm_payloads import (
    validate_recommendation as _validate_recommendation_impl,
)
from bumpkin.providers.llm_recommend import (
    get_recommendation as _get_recommendation_impl,
)
from bumpkin.providers.llm_transport import (
    LLMUnavailableError,
)
from bumpkin.providers.llm_transport import (
    normalize_request_endpoint as _normalize_request_endpoint_impl,
)
from bumpkin.providers.llm_transport import (
    post_json_request as _post_json_request_impl,
)
from bumpkin.providers.llm_transport import (
    provider_mode_for_endpoint as _provider_mode_for_endpoint_impl,
)
from bumpkin.providers.llm_transport import (
    request_headers as _request_headers_impl,
)
from bumpkin.providers.semantic import (
    classified_result as _classified_result_impl,
)
from bumpkin.providers.semantic import (
    manual_review_result as _manual_review_result_impl,
)
from bumpkin.providers.semantic import (
    no_bump_recommendation as _no_bump_recommendation_impl,
)
from bumpkin.providers.semantic import (
    semantic_fallback_recommendation as _semantic_fallback_recommendation_impl,
)
from bumpkin.providers.semantic import (
    stub_recommendation as _stub_recommendation_impl,
)

LABEL_PRIORITY = {"NO_BUMP": 0, "PATCH": 1, "MINOR": 2, "MAJOR": 3}

LLMResponseError = _LLMResponseError_impl


def _provider_mode_for_endpoint(endpoint: str) -> str:
    return _provider_mode_for_endpoint_impl(endpoint)


def _normalize_request_endpoint(endpoint: str) -> str:  # pyright: ignore[reportUnusedFunction]
    return _normalize_request_endpoint_impl(endpoint)


def _request_headers(token: str, endpoint: str) -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
    return _request_headers_impl(token, endpoint)


def _semantic_fallback_recommendation(
    *,
    diff_text: str,
    surface_area_hints: list[str] | None,
    truncated: bool,
) -> dict[str, Any]:
    return _semantic_fallback_recommendation_impl(
        diff_text=diff_text,
        surface_area_hints=surface_area_hints,
        truncated=truncated,
    )


def _classified_result(
    *,
    label: str,
    confidence: str,
    reasoning: str,
    changelog: str,
) -> dict[str, Any]:
    return _classified_result_impl(
        label=label,
        confidence=confidence,
        reasoning=reasoning,
        changelog=changelog,
    )


def _manual_review_result(
    *,
    reasoning: str,
) -> dict[str, Any]:
    return _manual_review_result_impl(reasoning=reasoning)


def get_stub_recommendation(truncated: bool) -> dict[str, Any]:
    return _stub_recommendation_impl(truncated)


def get_no_bump_recommendation(truncated: bool) -> dict[str, Any]:
    return _no_bump_recommendation_impl(truncated)


def validate_recommendation(payload: dict[str, Any]) -> dict[str, str]:
    return _validate_recommendation_impl(payload)


def _normalize_label(value: Any) -> str | None:  # pyright: ignore[reportUnusedFunction]
    return _normalize_label_impl(value)


def _normalize_confidence(value: Any) -> str | None:  # pyright: ignore[reportUnusedFunction]
    return _normalize_confidence_impl(value)


def _coerce_recommendation_payload(payload: object) -> dict[str, Any]:
    return _coerce_recommendation_payload_impl(payload)


def _build_messages(
    diff_text: str,
    language_group: str | None = None,
    prompt_version: str | None = None,
    surface_area_hints: list[str] | None = None,
    language_hints: list[str] | None = None,
) -> list[dict[str, str]]:
    return build_prompt_messages(
        diff_text=diff_text,
        language_group=language_group,
        prompt_version=prompt_version,
        surface_area_hints=surface_area_hints,
        language_hints=language_hints,
    )


def _split_diff_units_into_chunks(
    diff_units: list[tuple[str, str]],
    *,
    max_chunk_tokens: int,
    max_chunk_count: int,
) -> tuple[list[dict[str, Any]], int, set[str], set[str]]:
    return _split_diff_units_into_chunks_impl(
        diff_units,
        max_chunk_tokens=max_chunk_tokens,
        max_chunk_count=max_chunk_count,
    )


def _split_diff_into_chunks(
    diff_text: str,
    *,
    max_chunk_tokens: int,
    max_chunk_count: int,
) -> tuple[list[str], int]:
    return _split_diff_into_chunks_impl(
        diff_text,
        max_chunk_tokens=max_chunk_tokens,
        max_chunk_count=max_chunk_count,
    )


def _aggregate_chunk_recommendations(
    recommendations: list[dict[str, str]],
    *,
    truncated: bool,
) -> dict[str, Any]:
    return _aggregate_chunk_recommendations_impl(
        recommendations,
        truncated=truncated,
        valid_labels=VALID_LABELS,
        label_priority=LABEL_PRIORITY,
        aggregate_changelog=AGGREGATE_CHANGELOG,
    )


def _with_chunking_metadata(
    result: dict[str, Any],
    *,
    enabled: bool,
    chunk_count: int,
    succeeded: int,
    failed: int,
    skipped: int,
    max_chunk_tokens: int,
    max_chunk_count: int,
    failure_policy: str,
    files_total: int = 0,
    omitted_files: list[str] | None = None,
) -> dict[str, Any]:
    return _with_chunking_metadata_impl(
        result,
        enabled=enabled,
        chunk_count=chunk_count,
        succeeded=succeeded,
        failed=failed,
        skipped=skipped,
        max_chunk_tokens=max_chunk_tokens,
        max_chunk_count=max_chunk_count,
        failure_policy=failure_policy,
        files_total=files_total,
        omitted_files=omitted_files,
    )


def _extract_content(response_payload: dict[str, Any]) -> str:
    return _extract_content_impl(response_payload)


def _extract_json_payload(content: str) -> dict[str, Any]:
    return _extract_json_payload_impl(content)


def _call_github_models(
    token: str,
    model: str,
    diff_text: str,
    language_group: str | None,
    prompt_version: str | None,
    surface_area_hints: list[str] | None,
    language_hints: list[str] | None,
    endpoint: str,
    max_retries: int,
    request_timeout: int,
) -> dict[str, str]:
    if not token:
        raise LLMUnavailableError(
            "No token available for model provider. Provide MODELS_TOKEN, GITHUB_MODELS_TOKEN, "
            "or OPENROUTER_API_KEY/OPENROUTER_API."
        )

    payload = {
        "model": model,
        "messages": _build_messages(
            diff_text,
            language_group=language_group,
            prompt_version=prompt_version,
            surface_area_hints=surface_area_hints,
            language_hints=language_hints,
        ),
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_tokens": 400,
    }

    raw = _post_json_request_impl(
        endpoint=endpoint,
        token=token,
        payload=payload,
        max_retries=max_retries,
        request_timeout=request_timeout,
    )
    content = _extract_content(raw)
    parsed = _extract_json_payload(content)
    return validate_recommendation(_coerce_recommendation_payload(parsed))


def get_recommendation(
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
    return _get_recommendation_impl(
        provider_mode_for_endpoint_fn=_provider_mode_for_endpoint,
        get_stub_recommendation_fn=get_stub_recommendation,
        split_diff_units_into_chunks_fn=_split_diff_units_into_chunks,
        split_diff_into_chunks_fn=_split_diff_into_chunks,
        call_model_fn=_call_github_models,
        aggregate_chunk_recommendations_fn=_aggregate_chunk_recommendations,
        classified_result_fn=_classified_result,
        manual_review_result_fn=_manual_review_result,
        semantic_fallback_fn=_semantic_fallback_recommendation,
        with_chunking_metadata_fn=_with_chunking_metadata,
        mode=mode,
        diff_text=diff_text,
        truncated=truncated,
        language_group=language_group,
        prompt_version=prompt_version,
        surface_area_hints=surface_area_hints,
        language_hints=language_hints,
        model=model,
        fallback_model=fallback_model,
        endpoint=endpoint,
        token=token,
        use_semantic_fallback=use_semantic_fallback,
        max_retries=max_retries,
        request_timeout=request_timeout,
        chunking_enabled=chunking_enabled,
        chunk_max_tokens=chunk_max_tokens,
        chunk_max_count=chunk_max_count,
        chunk_failure_policy=chunk_failure_policy,
        diff_units=diff_units,
    )
