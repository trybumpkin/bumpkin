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

_provider_mode_for_endpoint = _provider_mode_for_endpoint_impl
_normalize_request_endpoint = _normalize_request_endpoint_impl
_request_headers = _request_headers_impl
_semantic_fallback_recommendation = _semantic_fallback_recommendation_impl
_classified_result = _classified_result_impl
_manual_review_result = _manual_review_result_impl
get_stub_recommendation = _stub_recommendation_impl
get_no_bump_recommendation = _no_bump_recommendation_impl
validate_recommendation = _validate_recommendation_impl
_normalize_label = _normalize_label_impl
_normalize_confidence = _normalize_confidence_impl
_coerce_recommendation_payload = _coerce_recommendation_payload_impl
_build_messages = build_prompt_messages
_split_diff_units_into_chunks = _split_diff_units_into_chunks_impl
_split_diff_into_chunks = _split_diff_into_chunks_impl


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


_with_chunking_metadata = _with_chunking_metadata_impl
_extract_content = _extract_content_impl
_extract_json_payload = _extract_json_payload_impl


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
            "No API key available for model provider. Provide BUMPKIN_API_KEY."
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
