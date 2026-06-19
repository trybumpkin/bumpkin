from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from bumpkin.io.tokens import is_github_models_endpoint
from bumpkin.orchestrator.court_payload import (
    extract_case_file_evidence_ids as _extract_case_file_evidence_ids,
)
from bumpkin.orchestrator.court_payload import (
    extract_content as _extract_content,
)
from bumpkin.orchestrator.court_payload import (
    extract_json_payload as _extract_json_payload,
)
from bumpkin.orchestrator.court_payload import (
    iter_json_object_slices as _iter_json_object_slices,
)
from bumpkin.orchestrator.court_payload import (
    normalize_label as _normalize_label,
)
from bumpkin.orchestrator.court_payload import (
    validate_court_payload as _validate_court_payload,
)
from bumpkin.retry import (
    apply_model_call_interval,
    compute_retry_delay,
    is_retryable_http_code,
    register_rate_limit_cooldown,
)

DEFAULT_MAX_OUTPUT_TOKENS = 400
REPAIR_MAX_OUTPUT_TOKENS = 260
COURT_SCHEMA_NAME = "compatibility_court_verdict_v1"
COURT_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "label": {"type": "string", "enum": ["MAJOR", "MINOR", "PATCH", "NO_BUMP"]},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "judge_summary": {"type": "string", "minLength": 12},
        "prosecutor_claims": {"type": "array", "items": {"type": "string"}},
        "defender_claims": {"type": "array", "items": {"type": "string"}},
        "accepted_arguments": {"type": "array", "items": {"type": "string"}},
        "rejected_arguments": {"type": "array", "items": {"type": "string"}},
        "unresolved_risks": {"type": "array", "items": {"type": "string"}},
        "accepted_evidence_ids": {"type": "array", "items": {"type": "string"}},
        "rejected_evidence_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "label",
        "confidence",
        "judge_summary",
        "prosecutor_claims",
        "defender_claims",
        "accepted_arguments",
        "rejected_arguments",
        "unresolved_risks",
        "accepted_evidence_ids",
        "rejected_evidence_ids",
    ],
}


def _request_headers(token: str, endpoint: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if is_github_models_endpoint(endpoint):
        headers["Accept"] = "application/vnd.github+json"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    return headers


def request_headers(token: str, endpoint: str) -> dict[str, str]:
    return _request_headers(token, endpoint)


def extract_content(response_payload: dict[str, Any]) -> str:
    return _extract_content(response_payload)


def iter_json_object_slices(text: str) -> list[str]:
    return _iter_json_object_slices(text)


def build_court_messages(
    *,
    case_file_text: str,
    engine_label: str,
    language_hints: list[str] | None = None,
) -> list[dict[str, str]]:
    system = (
        "You are Compatibility Court. Reason over the provided case file and return strict JSON only. "
        "Required keys: label, confidence, judge_summary, prosecutor_claims, defender_claims, "
        "accepted_arguments, rejected_arguments, unresolved_risks, accepted_evidence_ids, "
        "rejected_evidence_ids. "
        "label must be MAJOR|MINOR|PATCH|NO_BUMP. confidence must be high|medium|low. "
        "Every accepted/rejected evidence id must exist in case_file.evidence_records[]. "
        "Each claim should cite those IDs or file paths present in the case file. "
        "Do not include markdown."
    )
    user = (
        "Court protocol:\n"
        "1) Prosecutor argues for higher-impact bump from evidence.\n"
        "2) Defender argues for lower-impact bump from evidence.\n"
        "3) Judge issues final verdict with accepted/rejected arguments and unresolved risks.\n\n"
        f"Deterministic engine label: {engine_label}\n\n"
        + (
            "Language-specific API hints:\n"
            + "".join(f"- {hint}\n" for hint in language_hints)
            + "\n"
            if language_hints
            else ""
        )
        + "Case file:\n"
        + f"{case_file_text}\n"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _build_repair_messages(*, raw_output: str, fallback_label: str | None) -> list[dict[str, str]]:
    default_label = _normalize_label(fallback_label or "") or "PATCH"
    system = (
        "You repair malformed Compatibility Court output into strict JSON only. "
        "Return one JSON object with keys: label, confidence, judge_summary, "
        "prosecutor_claims, defender_claims, accepted_arguments, rejected_arguments, unresolved_risks, "
        "accepted_evidence_ids, rejected_evidence_ids. "
        "label must be MAJOR|MINOR|PATCH|NO_BUMP. confidence must be high|medium|low. "
        "No markdown, no prose."
    )
    user = (
        "Repair the malformed payload below.\n"
        f"If label is missing or truncated, use default label {default_label}.\n"
        "If confidence is missing, use low.\n"
        "If judge_summary is missing, provide one concise sentence.\n\n"
        "Malformed output:\n"
        f"{raw_output[:1500]}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _attempt_repair_payload(
    *,
    token: str,
    endpoint: str,
    model: str,
    raw_output: str,
    fallback_label: str | None,
    valid_evidence_ids: set[str] | None,
    request_timeout: int,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": _build_repair_messages(raw_output=raw_output, fallback_label=fallback_label),
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": COURT_SCHEMA_NAME,
                "strict": True,
                "schema": COURT_RESPONSE_SCHEMA,
            },
        },
        "temperature": 0,
        "max_tokens": REPAIR_MAX_OUTPUT_TOKENS,
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers=_request_headers(token, endpoint),
    )
    try:
        with urllib.request.urlopen(req, timeout=max(1, request_timeout)) as response:
            raw = json.loads(response.read().decode("utf-8"))
        return _validate_court_payload(
            _extract_json_payload(_extract_content(raw), fallback_label=fallback_label),
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


def _call_model(
    *,
    token: str,
    endpoint: str,
    model: str,
    messages: list[dict[str, str]],
    fallback_label: str | None,
    max_retries: int,
    request_timeout: int,
    valid_evidence_ids: set[str] | None = None,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": messages,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": COURT_SCHEMA_NAME,
                "strict": True,
                "schema": COURT_RESPONSE_SCHEMA,
            },
        },
        "temperature": 0,
        "max_tokens": DEFAULT_MAX_OUTPUT_TOKENS,
    }
    attempts = max(1, max_retries)
    retry_delays: list[float] = []
    last_error = "unknown"
    for attempt in range(attempts):
        apply_model_call_interval()
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers=_request_headers(token, endpoint),
        )
        try:
            with urllib.request.urlopen(req, timeout=max(1, request_timeout)) as response:
                raw = json.loads(response.read().decode("utf-8"))
            try:
                return _validate_court_payload(
                    _extract_json_payload(_extract_content(raw), fallback_label=fallback_label),
                    valid_evidence_ids=valid_evidence_ids,
                )
            except (ValueError, RuntimeError) as parse_err:
                raw_snapshot = json.dumps(raw, ensure_ascii=True)
                try:
                    return _attempt_repair_payload(
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
            if is_retryable_http_code(err.code) and attempt < attempts - 1:
                base_delays = (60.0, 90.0, 90.0) if err.code == 429 else (2.0, 4.0, 8.0)
                if err.code == 429:
                    register_rate_limit_cooldown(headers=err.headers, minimum_seconds=60.0)
                delay = compute_retry_delay(
                    attempt_index=attempt,
                    headers=err.headers,
                    base_delays=base_delays,
                )
                retry_delays.append(delay)
                time.sleep(delay)
                continue
            if retry_delays:
                last_error += f" retry_delays={retry_delays}"
            raise RuntimeError(last_error) from err
        except urllib.error.URLError as err:
            last_error = str(err.reason)
            if attempt < attempts - 1:
                delay = compute_retry_delay(attempt_index=attempt)
                retry_delays.append(delay)
                time.sleep(delay)
                continue
            if retry_delays:
                last_error += f" retry_delays={retry_delays}"
            raise RuntimeError(last_error) from err
        except TimeoutError as err:
            last_error = str(err) or "request timed out"
            if attempt < attempts - 1:
                delay = compute_retry_delay(attempt_index=attempt)
                retry_delays.append(delay)
                time.sleep(delay)
                continue
            if retry_delays:
                last_error += f" retry_delays={retry_delays}"
            raise RuntimeError(last_error) from err
        except (ValueError, RuntimeError) as err:
            last_error = str(err)
            if attempt < attempts - 1:
                delay = compute_retry_delay(attempt_index=attempt)
                retry_delays.append(delay)
                time.sleep(delay)
                continue
            if retry_delays:
                last_error += f" retry_delays={retry_delays}"
            raise RuntimeError(last_error) from err
    raise RuntimeError(last_error)


def _call_with_fallback(
    *,
    token: str,
    endpoint: str,
    model: str,
    fallback_model: str | None,
    messages: list[dict[str, str]],
    fallback_label: str | None,
    max_retries: int,
    request_timeout: int,
    valid_evidence_ids: set[str] | None = None,
) -> tuple[dict[str, Any], str]:
    try:
        return (
            _call_model(
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
                _call_model(
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


def run_court_advisory(
    *,
    mode: str,
    model: str,
    fallback_model: str | None,
    endpoint: str,
    token: str,
    max_retries: int,
    request_timeout: int,
    engine_label: str | None,
    case_file_text: str,
    language_hints: list[str] | None = None,
) -> tuple[dict[str, Any], str | None, str | None]:
    if not engine_label:
        return (
            {
                "status": "skipped",
                "label": None,
                "confidence": None,
                "judge_summary": "Court advisory skipped because no deterministic classification was available.",
                "prosecutor_claims": [],
                "defender_claims": [],
                "accepted_arguments": [],
                "rejected_arguments": [],
                "unresolved_risks": [],
                "accepted_evidence_ids": [],
                "rejected_evidence_ids": [],
                "disagreement_reason": None,
            },
            None,
            None,
        )

    normalized_mode = mode.strip().lower()
    if normalized_mode == "stub":
        return (
            {
                "status": "aligned",
                "label": engine_label,
                "confidence": "high",
                "judge_summary": "Stub court advisory mirrors deterministic decision.",
                "prosecutor_claims": [
                    "Stub prosecutor: deterministic evidence indicates the selected impact."
                ],
                "defender_claims": ["Stub defender: no contradictory evidence in stub mode."],
                "accepted_arguments": ["Deterministic evidence chain is accepted in stub mode."],
                "rejected_arguments": [],
                "unresolved_risks": [],
                "accepted_evidence_ids": [],
                "rejected_evidence_ids": [],
                "disagreement_reason": None,
            },
            None,
            "stub",
        )

    if not token:
        return (
            {
                "status": "degraded",
                "label": None,
                "confidence": None,
                "judge_summary": "Court advisory degraded because no model token was available.",
                "prosecutor_claims": [],
                "defender_claims": [],
                "accepted_arguments": [],
                "rejected_arguments": [],
                "unresolved_risks": [],
                "accepted_evidence_ids": [],
                "rejected_evidence_ids": [],
                "disagreement_reason": None,
            },
            "missing_model_token",
            None,
        )

    messages = build_court_messages(
        case_file_text=case_file_text,
        engine_label=engine_label,
        language_hints=language_hints,
    )
    valid_evidence_ids = _extract_case_file_evidence_ids(case_file_text)
    try:
        parsed, used_model = _call_with_fallback(
            token=token,
            endpoint=endpoint,
            model=model,
            fallback_model=fallback_model,
            messages=messages,
            fallback_label=engine_label,
            valid_evidence_ids=valid_evidence_ids,
            max_retries=max_retries,
            request_timeout=request_timeout,
        )
    except RuntimeError as err:
        return (
            {
                "status": "degraded",
                "label": None,
                "confidence": None,
                "judge_summary": "Court advisory degraded because the provider call failed.",
                "prosecutor_claims": [],
                "defender_claims": [],
                "accepted_arguments": [],
                "rejected_arguments": [],
                "unresolved_risks": [],
                "accepted_evidence_ids": [],
                "rejected_evidence_ids": [],
                "disagreement_reason": None,
            },
            str(err),
            None,
        )

    if parsed["label"] == engine_label:
        parsed["status"] = "aligned"
        parsed["disagreement_reason"] = None
        return parsed, None, used_model

    parsed["status"] = "manual_review"
    parsed["disagreement_reason"] = (
        f"Court verdict {parsed['label']} disagreed with deterministic decision {engine_label}."
    )
    return parsed, None, used_model
