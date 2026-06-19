from __future__ import annotations

import json
import re
from typing import Any, cast

from bumpkin.prompt_pack import build_messages as build_prompt_messages
from bumpkin.prompt_pack import get_prompt_metadata
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

VALID_LABELS = {"MAJOR", "MINOR", "PATCH", "NO_BUMP"}
VALID_CONFIDENCE = {"high", "medium", "low"}
LABEL_PRIORITY = {"NO_BUMP": 0, "PATCH": 1, "MINOR": 2, "MAJOR": 3}
AGGREGATE_CHANGELOG = {
    "MAJOR": "feat: introduce breaking public api changes",
    "MINOR": "feat: add backward-compatible api changes",
    "PATCH": "fix: internal implementation update",
    "NO_BUMP": "chore: no release required",
}
CHANGELOG_PATTERN = re.compile(
    r"^(feat|fix|chore|refactor|perf|docs|build|ci|test|style)(\([^)]+\))?(!)?:\s+\S"
)


class LLMResponseError(RuntimeError):
    pass


def _as_dict(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return cast("dict[str, Any]", value)


def _as_object_list(value: object) -> list[object] | None:
    if not isinstance(value, list):
        return None
    return cast("list[object]", value)


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
    label = str(payload.get("label", "")).strip().upper()
    confidence = str(payload.get("confidence", "")).strip().lower()
    reasoning = str(payload.get("reasoning", "")).strip()
    changelog = str(payload.get("changelog", "")).strip()

    if label not in VALID_LABELS:
        raise LLMResponseError(f"Invalid label in model output: {label!r}")
    if confidence not in VALID_CONFIDENCE:
        raise LLMResponseError(f"Invalid confidence in model output: {confidence!r}")
    if len(reasoning) < 20:
        raise LLMResponseError("Model reasoning is too short; expected at least 20 chars.")
    if not changelog:
        raise LLMResponseError("Model changelog field is empty.")
    if not CHANGELOG_PATTERN.match(changelog):
        raise LLMResponseError("Model changelog must start with one of feat:, fix:, or chore:.")

    return {
        "label": label,
        "confidence": confidence,
        "reasoning": reasoning,
        "changelog": changelog,
    }


def _normalize_label(value: Any) -> str | None:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    mapping = {
        "major": "MAJOR",
        "breaking": "MAJOR",
        "breaking_change": "MAJOR",
        "minor": "MINOR",
        "feature": "MINOR",
        "patch": "PATCH",
        "fix": "PATCH",
        "bugfix": "PATCH",
        "bug_fix": "PATCH",
        "no_bump": "NO_BUMP",
        "nobump": "NO_BUMP",
        "no_release": "NO_BUMP",
        "none": "NO_BUMP",
        "skip": "NO_BUMP",
    }
    if text in mapping:
        return mapping[text]
    candidate = text.upper()
    if candidate in VALID_LABELS:
        return candidate
    return None


def _normalize_confidence(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    mapping = {
        "high": "high",
        "medium": "medium",
        "low": "low",
        "strong": "high",
        "moderate": "medium",
        "weak": "low",
    }
    if text in mapping:
        return mapping[text]
    return None


def _coerce_recommendation_payload(payload: object) -> dict[str, Any]:
    payload_dict = _as_dict(payload)
    if payload_dict is None:
        return {}

    label = _normalize_label(
        payload_dict.get("label")
        or payload_dict.get("version_bump")
        or payload_dict.get("bump")
        or payload_dict.get("recommendation")
    )
    confidence = _normalize_confidence(
        payload_dict.get("confidence") or payload_dict.get("certainty")
    )
    reasoning = str(
        payload_dict.get("reasoning")
        or payload_dict.get("rationale")
        or payload_dict.get("reason")
        or payload_dict.get("explanation")
        or ""
    ).strip()
    changelog = str(
        payload_dict.get("changelog")
        or payload_dict.get("commit_message")
        or payload_dict.get("conventional_commit")
        or ""
    ).strip()

    if label and not changelog:
        changelog = AGGREGATE_CHANGELOG.get(label, "chore: no release required")
    if label and len(reasoning) < 20:
        reasoning = (
            f"Model advisory selected {label} after evaluating API-impact signals from the diff."
        )

    coerced = dict(payload_dict)
    if label:
        coerced["label"] = label
    if confidence:
        coerced["confidence"] = confidence
    if reasoning:
        coerced["reasoning"] = reasoning
    if changelog:
        coerced["changelog"] = changelog
    return coerced


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
    choices = _as_object_list(response_payload.get("choices"))
    if not choices:
        raise LLMResponseError("Missing choices in model response.")

    first_choice = _as_dict(choices[0])
    if first_choice is None:
        raise LLMResponseError("Missing choices in model response.")
    message = _as_dict(first_choice.get("message")) or {}
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    content_dict = _as_dict(content)
    if content_dict is not None:
        text = content_dict.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    content_list = _as_object_list(content)
    if content_list is not None:
        # Some OpenAI-compatible providers (including OpenRouter) can return
        # segmented content blocks instead of a plain string.
        text_parts: list[str] = []
        for item in content_list:
            item_dict = _as_dict(item)
            if item_dict is None:
                continue
            text = item_dict.get("text")
            if isinstance(text, str) and text.strip():
                text_parts.append(text.strip())
        if text_parts:
            return "\n".join(text_parts).strip()
    tool_calls = _as_object_list(message.get("tool_calls"))
    if tool_calls is not None:
        for tool_call in tool_calls:
            tool_call_dict = _as_dict(tool_call)
            if tool_call_dict is None:
                continue
            function = _as_dict(tool_call_dict.get("function"))
            if function is None:
                continue
            arguments = function.get("arguments")
            if isinstance(arguments, str) and arguments.strip():
                return arguments.strip()
    raise LLMResponseError("Missing message.content in model response.")


def _extract_json_payload(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1]).strip()
            if text.startswith("json"):
                text = text[4:].lstrip()

    try:
        parsed = json.loads(text)
        parsed_dict = _as_dict(parsed)
        if parsed_dict is not None:
            return parsed_dict
        if isinstance(parsed, str):
            nested = json.loads(parsed)
            nested_dict = _as_dict(nested)
            if nested_dict is not None:
                return nested_dict
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            parsed_dict = _as_dict(parsed)
            if parsed_dict is not None:
                return parsed_dict
        except json.JSONDecodeError:
            pass

    raise LLMResponseError("Model returned non-JSON output.")


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


def _call_chunk_with_fallback(
    *,
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
        recommendation = _call_github_models(
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
                recommendation = _call_github_models(
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
    normalized_mode = mode.strip().lower()
    if normalized_mode not in {"auto", "stub", "github-models", "openrouter"}:
        raise ValueError(f"Unsupported mode: {mode!r}")

    if normalized_mode == "stub":
        return get_stub_recommendation(truncated), "stub", None, "stub"

    model_mode = (
        "openrouter" if normalized_mode == "openrouter" else _provider_mode_for_endpoint(endpoint)
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

    def _single_shot() -> tuple[dict[str, Any], str, str | None, str | None]:
        try:
            recommendation = _call_chunk_with_fallback(
                token=token,
                model=model,
                fallback_model=fallback_model,
                chunk_diff=diff_text,
                language_group=prompt_metadata.language_group,
                prompt_version=prompt_metadata.prompt_version,
                surface_area_hints=surface_area_hints,
                language_hints=language_hints,
                endpoint=endpoint,
                max_retries=max_retries,
                request_timeout=request_timeout,
            )
            parsed, used_model = recommendation
            if truncated:
                parsed["reasoning"] += " (diff truncated; review manually)"
            result = _classified_result(
                label=parsed["label"],
                confidence=parsed["confidence"],
                reasoning=parsed["reasoning"],
                changelog=parsed["changelog"],
            )
            result = _with_chunking_metadata(
                result,
                enabled=False,
                chunk_count=1,
                succeeded=1,
                failed=0,
                skipped=0,
                max_chunk_tokens=chunk_max_tokens,
                max_chunk_count=chunk_max_count,
                failure_policy=normalized_chunk_failure_policy,
                files_total=files_total,
                omitted_files=single_shot_omitted_files,
            )
            return result, model_mode, None, used_model
        except LLMUnavailableError as err:
            if use_semantic_fallback:
                fallback_result = _semantic_fallback_recommendation(
                    diff_text=diff_text,
                    surface_area_hints=surface_area_hints,
                    truncated=truncated,
                )
                fallback_result = _with_chunking_metadata(
                    fallback_result,
                    enabled=False,
                    chunk_count=1,
                    succeeded=0,
                    failed=1,
                    skipped=0,
                    max_chunk_tokens=chunk_max_tokens,
                    max_chunk_count=chunk_max_count,
                    failure_policy=normalized_chunk_failure_policy,
                    files_total=files_total,
                    omitted_files=known_files,
                )
                return (
                    fallback_result,
                    "fallback-heuristic",
                    str(err),
                    "semantic-fallback",
                )
            manual = _manual_review_result(
                reasoning=(
                    "Automatic model analysis was unavailable. Please classify this PR manually."
                )
            )
            manual = _with_chunking_metadata(
                manual,
                enabled=False,
                chunk_count=1,
                succeeded=0,
                failed=1,
                skipped=0,
                max_chunk_tokens=chunk_max_tokens,
                max_chunk_count=chunk_max_count,
                failure_policy=normalized_chunk_failure_policy,
                files_total=files_total,
                omitted_files=known_files,
            )
            return manual, model_mode, str(err), None
        except LLMResponseError as err:
            if use_semantic_fallback:
                fallback_result = _semantic_fallback_recommendation(
                    diff_text=diff_text,
                    surface_area_hints=surface_area_hints,
                    truncated=truncated,
                )
                fallback_result = _with_chunking_metadata(
                    fallback_result,
                    enabled=False,
                    chunk_count=1,
                    succeeded=0,
                    failed=1,
                    skipped=0,
                    max_chunk_tokens=chunk_max_tokens,
                    max_chunk_count=chunk_max_count,
                    failure_policy=normalized_chunk_failure_policy,
                    files_total=files_total,
                    omitted_files=known_files,
                )
                return (
                    fallback_result,
                    "fallback-heuristic",
                    str(err),
                    "semantic-fallback",
                )
            manual = _manual_review_result(
                reasoning=(
                    "Automatic model analysis returned an invalid response. "
                    "Please classify this PR manually."
                )
            )
            manual = _with_chunking_metadata(
                manual,
                enabled=False,
                chunk_count=1,
                succeeded=0,
                failed=1,
                skipped=0,
                max_chunk_tokens=chunk_max_tokens,
                max_chunk_count=chunk_max_count,
                failure_policy=normalized_chunk_failure_policy,
                files_total=files_total,
                omitted_files=known_files,
            )
            return manual, model_mode, str(err), None

    if not chunking_enabled:
        return _single_shot()

    chunk_payloads: list[dict[str, Any]]
    skipped_chunks: int
    omitted_due_to_chunk_limit: set[str]
    all_chunk_files: set[str]
    if normalized_units:
        chunk_payloads, skipped_chunks, all_chunk_files, omitted_due_to_chunk_limit = (
            _split_diff_units_into_chunks(
                normalized_units,
                max_chunk_tokens=chunk_max_tokens,
                max_chunk_count=chunk_max_count,
            )
        )
    else:
        chunks, skipped_chunks = _split_diff_into_chunks(
            diff_text,
            max_chunk_tokens=chunk_max_tokens,
            max_chunk_count=chunk_max_count,
        )
        chunk_payloads = [{"text": chunk, "files": set()} for chunk in chunks]
        all_chunk_files = set()
        omitted_due_to_chunk_limit = set()

    if not chunk_payloads:
        return _single_shot()

    successful: list[dict[str, str]] = []
    chunk_errors: list[str] = []
    models_used: list[str] = []
    covered_files: set[str] = set()
    failed_files: set[str] = set()
    for chunk in chunk_payloads:
        chunk_text = str(chunk["text"])
        chunk_files = set(chunk["files"])
        try:
            parsed, used_model = _call_chunk_with_fallback(
                token=token,
                model=model,
                fallback_model=fallback_model,
                chunk_diff=chunk_text,
                language_group=prompt_metadata.language_group,
                prompt_version=prompt_metadata.prompt_version,
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
        manual = _manual_review_result(
            reasoning=(
                "Chunked model analysis omitted one or more files because chunk limits were reached. "
                "Please review manually."
            )
        )
        manual = _with_chunking_metadata(
            manual,
            enabled=True,
            chunk_count=chunk_count,
            succeeded=success_count,
            failed=failed_count,
            skipped=skipped_chunks,
            max_chunk_tokens=chunk_max_tokens,
            max_chunk_count=chunk_max_count,
            failure_policy=normalized_chunk_failure_policy,
            files_total=files_total_for_metadata,
            omitted_files=omitted_files,
        )
        return manual, model_mode, "chunk_limit_coverage_gap", "mixed"

    if failed_count == 0:
        aggregated = _aggregate_chunk_recommendations(
            successful,
            truncated=truncated,
        )
        aggregated = _with_chunking_metadata(
            aggregated,
            enabled=True,
            chunk_count=chunk_count,
            succeeded=success_count,
            failed=failed_count,
            skipped=skipped_chunks,
            max_chunk_tokens=chunk_max_tokens,
            max_chunk_count=chunk_max_count,
            failure_policy=normalized_chunk_failure_policy,
            files_total=files_total_for_metadata,
            omitted_files=omitted_files,
        )
        model_used = models_used[0] if len(set(models_used)) == 1 else "mixed"
        return aggregated, model_mode, None, model_used

    fallback_reason = "; ".join(chunk_errors[:2])
    if success_count == 0:
        if use_semantic_fallback:
            fallback_result = _semantic_fallback_recommendation(
                diff_text=diff_text,
                surface_area_hints=surface_area_hints,
                truncated=truncated,
            )
            fallback_result = _with_chunking_metadata(
                fallback_result,
                enabled=True,
                chunk_count=chunk_count,
                succeeded=success_count,
                failed=failed_count,
                skipped=skipped_chunks,
                max_chunk_tokens=chunk_max_tokens,
                max_chunk_count=chunk_max_count,
                failure_policy=normalized_chunk_failure_policy,
                files_total=files_total_for_metadata,
                omitted_files=omitted_files,
            )
            return (
                fallback_result,
                "fallback-heuristic",
                fallback_reason,
                "semantic-fallback",
            )
        manual = _manual_review_result(
            reasoning=(
                "Chunked model analysis failed for all chunks. Please classify this PR manually."
            )
        )
        manual = _with_chunking_metadata(
            manual,
            enabled=True,
            chunk_count=chunk_count,
            succeeded=success_count,
            failed=failed_count,
            skipped=skipped_chunks,
            max_chunk_tokens=chunk_max_tokens,
            max_chunk_count=chunk_max_count,
            failure_policy=normalized_chunk_failure_policy,
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
    if normalized_chunk_failure_policy == "PATCH":
        partial = _classified_result(
            label="PATCH",
            confidence="low",
            reasoning=reasoning,
            changelog="fix: conservative patch bump due to partial chunk failures",
        )
    else:
        partial = _manual_review_result(reasoning=reasoning)

    partial = _with_chunking_metadata(
        partial,
        enabled=True,
        chunk_count=chunk_count,
        succeeded=success_count,
        failed=failed_count,
        skipped=skipped_chunks,
        max_chunk_tokens=chunk_max_tokens,
        max_chunk_count=chunk_max_count,
        failure_policy=normalized_chunk_failure_policy,
        files_total=files_total_for_metadata,
        omitted_files=omitted_files,
    )
    return partial, model_mode, fallback_reason, "mixed"
