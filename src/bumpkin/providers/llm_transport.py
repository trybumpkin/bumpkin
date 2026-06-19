from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, cast

from bumpkin.io.tokens import is_github_models_endpoint, is_openrouter_endpoint
from bumpkin.retry import (
    apply_model_call_interval,
    compute_retry_delay,
    is_retryable_http_code,
    register_rate_limit_cooldown,
)


class LLMUnavailableError(RuntimeError):
    pass


def provider_mode_for_endpoint(endpoint: str) -> str:
    if is_openrouter_endpoint(endpoint):
        return "openrouter"
    if is_github_models_endpoint(endpoint):
        return "github-models"
    return "openai-compatible"


def normalize_request_endpoint(endpoint: str) -> str:
    normalized = endpoint.strip()
    if not normalized:
        return normalized
    lowered = normalized.lower()
    if lowered.endswith(("/chat/completions", "/responses")):
        return normalized
    return normalized.rstrip("/") + "/chat/completions"


def request_headers(token: str, endpoint: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if provider_mode_for_endpoint(endpoint) == "github-models":
        headers["Accept"] = "application/vnd.github+json"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
        return headers

    # OpenRouter supports these optional headers for routing/analytics.
    referer = os.getenv("OPENROUTER_HTTP_REFERER", "").strip()
    app_title = os.getenv("OPENROUTER_TITLE", "bumpkin").strip()
    if referer:
        headers["HTTP-Referer"] = referer
    if app_title:
        headers["X-Title"] = app_title
    return headers


def post_json_request(
    *,
    endpoint: str,
    token: str,
    payload: dict[str, Any],
    max_retries: int,
    request_timeout: int,
) -> dict[str, Any]:
    attempts = max(1, max_retries)
    retry_delays: list[float] = []
    last_error: str | None = None

    for attempt in range(attempts):
        apply_model_call_interval()
        request_endpoint = normalize_request_endpoint(endpoint)
        req = urllib.request.Request(
            request_endpoint,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers=request_headers(token, endpoint),
        )
        try:
            with urllib.request.urlopen(req, timeout=max(1, request_timeout)) as response:
                raw_obj: object = json.loads(response.read().decode("utf-8"))
                if isinstance(raw_obj, dict):
                    return cast("dict[str, Any]", raw_obj)
                raise LLMUnavailableError("Model response body was not a JSON object.")
        except urllib.error.HTTPError as err:
            code = err.code
            body = err.read().decode("utf-8", errors="replace")
            last_error = f"HTTP {code}: {body[:300]}"
            if is_retryable_http_code(code) and attempt < attempts - 1:
                base_delays = (60.0, 90.0, 90.0) if code == 429 else (2.0, 4.0, 8.0)
                if code == 429:
                    register_rate_limit_cooldown(headers=err.headers, minimum_seconds=60.0)
                retry_delay = compute_retry_delay(
                    attempt_index=attempt,
                    headers=err.headers,
                    base_delays=base_delays,
                )
                retry_delays.append(retry_delay)
                time.sleep(retry_delay)
                continue
            if retry_delays:
                last_error += f" retry_delays={retry_delays}"
            raise LLMUnavailableError(last_error) from err
        except urllib.error.URLError as err:
            last_error = str(err.reason)
            if attempt < attempts - 1:
                retry_delay = compute_retry_delay(attempt_index=attempt)
                retry_delays.append(retry_delay)
                time.sleep(retry_delay)
                continue
            if retry_delays:
                last_error += f" retry_delays={retry_delays}"
            raise LLMUnavailableError(last_error) from err
        except TimeoutError as err:
            last_error = str(err) or "request timed out"
            if attempt < attempts - 1:
                retry_delay = compute_retry_delay(attempt_index=attempt)
                retry_delays.append(retry_delay)
                time.sleep(retry_delay)
                continue
            if retry_delays:
                last_error += f" retry_delays={retry_delays}"
            raise LLMUnavailableError(last_error) from err

    provider_name = provider_mode_for_endpoint(endpoint)
    raise LLMUnavailableError(last_error or f"Failed to call {provider_name} model API.")
