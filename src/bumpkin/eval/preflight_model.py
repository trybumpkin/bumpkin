from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from bumpkin.analysis.language import get_language_hints_for_groups
from bumpkin.eval.preflight_errors import categorize_failure_reason
from bumpkin.providers.llm import get_recommendation


def invoke_recommend_fn(
    recommend_fn: Callable[..., tuple[dict[str, Any], str, str | None, str | None]], **kwargs: Any
) -> tuple[dict[str, Any], str, str | None, str | None]:
    signature = inspect.signature(recommend_fn)
    accepts_kwargs = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    if accepts_kwargs:
        return recommend_fn(**kwargs)
    filtered = {key: value for key, value in kwargs.items() if key in signature.parameters}
    return recommend_fn(**filtered)


def normalize_recommendation_result(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("status") in {"classified", "manual_review"}:
        return result
    required = ("label", "confidence", "reasoning", "changelog")
    if all(isinstance(result.get(key), str) for key in required):
        normalized = dict(result)
        normalized["status"] = "classified"
        return normalized
    return result


def run_eval_preflight(
    *,
    mode: str,
    language_group: str,
    prompt_version: str,
    model: str,
    endpoint: str,
    token: str,
    max_retries: int,
    request_timeout: int = 45,
    recommend_fn: Callable[
        ..., tuple[dict[str, Any], str, str | None, str | None]
    ] = get_recommendation,
) -> dict[str, Any]:
    normalized_mode = mode.strip().lower()
    if normalized_mode == "stub":
        return {
            "status": "skipped",
            "reason": "stub mode does not require model preflight.",
            "failure_category": None,
            "failure_reason": None,
            "mode_used": "stub",
            "model_used": "stub",
        }
    synthetic_diff = (
        "+ export function ping() {}"
        if language_group == "javascript-typescript"
        else "+ public API delta"
    )
    result, mode_used, fallback_reason, model_used = invoke_recommend_fn(
        recommend_fn,
        mode=mode,
        diff_text=synthetic_diff,
        truncated=False,
        language_group=language_group,
        prompt_version=prompt_version,
        surface_area_hints=None,
        language_hints=get_language_hints_for_groups([language_group]),
        model=model,
        fallback_model=None,
        endpoint=endpoint,
        token=token,
        max_retries=max_retries,
        request_timeout=request_timeout,
    )
    result = normalize_recommendation_result(result)
    if result.get("status") == "classified":
        if mode_used not in {"github-models", "openrouter", "openai-compatible"}:
            failure_reason = (
                f"model preflight degraded to {mode_used} (model_used={model_used or 'n/a'})."
            )
            if fallback_reason:
                failure_reason += f" root_cause={fallback_reason}"
            return {
                "status": "failed",
                "reason": "model preflight succeeded only via fallback/degraded mode.",
                "failure_category": categorize_failure_reason(fallback_reason) or "degraded_mode",
                "failure_reason": failure_reason,
                "mode_used": mode_used,
                "model_used": model_used,
            }
        return {
            "status": "ok",
            "reason": "model preflight succeeded.",
            "failure_category": None,
            "failure_reason": None,
            "mode_used": mode_used,
            "model_used": model_used,
        }
    return {
        "status": "failed",
        "reason": "model preflight returned manual_review.",
        "failure_category": categorize_failure_reason(fallback_reason),
        "failure_reason": fallback_reason,
        "mode_used": mode_used,
        "model_used": model_used,
    }
