from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from bumpkin.io.tokens import is_github_models_endpoint
from bumpkin.retry import (
    apply_model_call_interval,
    compute_retry_delay,
    is_retryable_http_code,
    register_rate_limit_cooldown,
)


def request_headers(token: str, endpoint: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if is_github_models_endpoint(endpoint):
        headers["Accept"] = "application/vnd.github+json"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    return headers


def _as_response_object(value: object, *, error_message: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(error_message)
    return value


def attempt_repair_payload(
    *,
    token: str,
    endpoint: str,
    model: str,
    raw_output: str,
    fallback_label: str | None,
    valid_evidence_ids: set[str] | None,
    request_timeout: int,
    schema_name: str,
    response_schema: dict[str, Any],
    max_output_tokens: int,
    request_headers_fn: Callable[[str, str], dict[str, str]],
    build_repair_messages_fn: Callable[..., list[dict[str, str]]],
    extract_content_fn: Callable[[dict[str, Any]], str],
    extract_json_payload_fn: Callable[..., dict[str, Any]],
    validate_court_payload_fn: Callable[..., dict[str, Any]],
    request_factory: Callable[..., Any] = urllib.request.Request,
    urlopen_fn: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": build_repair_messages_fn(
            raw_output=raw_output,
            fallback_label=fallback_label,
        ),
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": response_schema,
            },
        },
        "temperature": 0,
        "max_tokens": max_output_tokens,
    }
    request = request_factory(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers=request_headers_fn(token, endpoint),
    )
    try:
        with urlopen_fn(request, timeout=max(1, request_timeout)) as response:
            raw_obj: object = json.loads(response.read().decode("utf-8"))
        raw = _as_response_object(raw_obj, error_message="repair_response_not_object")
        return validate_court_payload_fn(
            extract_json_payload_fn(
                extract_content_fn(raw),
                fallback_label=fallback_label,
            ),
            valid_evidence_ids=valid_evidence_ids,
        )
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"repair_http_{err.code}: {body[:180]}") from err
    except urllib.error.URLError as err:
        raise RuntimeError(f"repair_url_error: {err.reason}") from err
    except TimeoutError as err:
        raise RuntimeError(str(err) or "repair request timed out") from err
    except (ValueError, RuntimeError) as err:
        raise RuntimeError(f"repair_parse_error: {err}") from err


def call_model(
    *,
    token: str,
    endpoint: str,
    model: str,
    messages: list[dict[str, str]],
    fallback_label: str | None,
    max_retries: int,
    request_timeout: int,
    valid_evidence_ids: set[str] | None,
    schema_name: str,
    response_schema: dict[str, Any],
    max_output_tokens: int,
    request_headers_fn: Callable[[str, str], dict[str, str]],
    extract_content_fn: Callable[[dict[str, Any]], str],
    extract_json_payload_fn: Callable[..., dict[str, Any]],
    validate_court_payload_fn: Callable[..., dict[str, Any]],
    attempt_repair_payload_fn: Callable[..., dict[str, Any]],
    apply_model_call_interval_fn: Callable[..., object] = apply_model_call_interval,
    compute_retry_delay_fn: Callable[..., float] = compute_retry_delay,
    is_retryable_http_code_fn: Callable[[int], bool] = is_retryable_http_code,
    register_rate_limit_cooldown_fn: Callable[..., object] = register_rate_limit_cooldown,
    request_factory: Callable[..., Any] = urllib.request.Request,
    urlopen_fn: Callable[..., Any] = urllib.request.urlopen,
    sleep_fn: Callable[[float], object] = time.sleep,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": messages,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": response_schema,
            },
        },
        "temperature": 0,
        "max_tokens": max_output_tokens,
    }
    attempts = max(1, max_retries)
    retry_delays: list[float] = []
    last_error = "unknown"
    for attempt in range(attempts):
        apply_model_call_interval_fn()
        request = request_factory(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers=request_headers_fn(token, endpoint),
        )
        try:
            with urlopen_fn(request, timeout=max(1, request_timeout)) as response:
                raw_obj: object = json.loads(response.read().decode("utf-8"))
            raw = _as_response_object(raw_obj, error_message="response_not_object")
            try:
                return validate_court_payload_fn(
                    extract_json_payload_fn(
                        extract_content_fn(raw),
                        fallback_label=fallback_label,
                    ),
                    valid_evidence_ids=valid_evidence_ids,
                )
            except (ValueError, RuntimeError) as parse_err:
                raw_snapshot = json.dumps(raw, ensure_ascii=True)
                try:
                    return attempt_repair_payload_fn(
                        token=token,
                        endpoint=endpoint,
                        model=model,
                        raw_output=raw_snapshot,
                        fallback_label=fallback_label,
                        valid_evidence_ids=valid_evidence_ids,
                        request_timeout=request_timeout,
                    )
                except RuntimeError as repair_err:
                    raise RuntimeError(f"{parse_err}; repair_failed={repair_err}") from repair_err
        except urllib.error.HTTPError as err:
            body = err.read().decode("utf-8", errors="replace")
            last_error = f"HTTP {err.code}: {body[:280]}"
            if is_retryable_http_code_fn(err.code) and attempt < attempts - 1:
                base_delays = (60.0, 90.0, 90.0) if err.code == 429 else (2.0, 4.0, 8.0)
                if err.code == 429:
                    register_rate_limit_cooldown_fn(headers=err.headers, minimum_seconds=60.0)
                delay = compute_retry_delay_fn(
                    attempt_index=attempt,
                    headers=err.headers,
                    base_delays=base_delays,
                )
                retry_delays.append(delay)
                sleep_fn(delay)
                continue
            if retry_delays:
                last_error += f" retry_delays={retry_delays}"
            raise RuntimeError(last_error) from err
        except urllib.error.URLError as err:
            last_error = str(err.reason)
            if attempt < attempts - 1:
                delay = compute_retry_delay_fn(attempt_index=attempt)
                retry_delays.append(delay)
                sleep_fn(delay)
                continue
            if retry_delays:
                last_error += f" retry_delays={retry_delays}"
            raise RuntimeError(last_error) from err
        except TimeoutError as err:
            last_error = str(err) or "request timed out"
            if attempt < attempts - 1:
                delay = compute_retry_delay_fn(attempt_index=attempt)
                retry_delays.append(delay)
                sleep_fn(delay)
                continue
            if retry_delays:
                last_error += f" retry_delays={retry_delays}"
            raise RuntimeError(last_error) from err
        except (ValueError, RuntimeError) as err:
            last_error = str(err)
            if attempt < attempts - 1:
                delay = compute_retry_delay_fn(attempt_index=attempt)
                retry_delays.append(delay)
                sleep_fn(delay)
                continue
            if retry_delays:
                last_error += f" retry_delays={retry_delays}"
            raise RuntimeError(last_error) from err
    raise RuntimeError(last_error)


def call_with_fallback(
    *,
    token: str,
    endpoint: str,
    model: str,
    fallback_model: str | None,
    messages: list[dict[str, str]],
    fallback_label: str | None,
    max_retries: int,
    request_timeout: int,
    valid_evidence_ids: set[str] | None,
    call_model_fn: Callable[..., dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    try:
        return (
            call_model_fn(
                token=token,
                endpoint=endpoint,
                model=model,
                messages=messages,
                fallback_label=fallback_label,
                valid_evidence_ids=valid_evidence_ids,
                max_retries=max_retries,
                request_timeout=request_timeout,
            ),
            model,
        )
    except RuntimeError as primary_err:
        candidate = (fallback_model or "").strip()
        if not candidate or candidate == model:
            raise RuntimeError(str(primary_err)) from primary_err
        try:
            return (
                call_model_fn(
                    token=token,
                    endpoint=endpoint,
                    model=candidate,
                    messages=messages,
                    fallback_label=fallback_label,
                    valid_evidence_ids=valid_evidence_ids,
                    max_retries=max_retries,
                    request_timeout=request_timeout,
                ),
                candidate,
            )
        except RuntimeError as fallback_err:
            raise RuntimeError(
                f"Primary model failed: {primary_err}. Fallback model failed: {fallback_err}."
            ) from fallback_err
