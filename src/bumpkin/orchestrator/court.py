from __future__ import annotations

import urllib.request
from typing import Any

from bumpkin.orchestrator import court_messages as orchestrator_court_messages
from bumpkin.orchestrator import court_transport as orchestrator_court_transport
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
    return orchestrator_court_transport.request_headers(token, endpoint)


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
    return orchestrator_court_messages.build_court_messages(
        case_file_text=case_file_text,
        engine_label=engine_label,
        language_hints=language_hints,
    )


def _build_repair_messages(*, raw_output: str, fallback_label: str | None) -> list[dict[str, str]]:
    return orchestrator_court_messages.build_repair_messages(
        raw_output=raw_output,
        fallback_label=fallback_label,
    )


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
    return orchestrator_court_transport.attempt_repair_payload(
        token=token,
        endpoint=endpoint,
        model=model,
        raw_output=raw_output,
        fallback_label=fallback_label,
        valid_evidence_ids=valid_evidence_ids,
        request_timeout=request_timeout,
        schema_name=COURT_SCHEMA_NAME,
        response_schema=COURT_RESPONSE_SCHEMA,
        max_output_tokens=REPAIR_MAX_OUTPUT_TOKENS,
        request_headers_fn=_request_headers,
        build_repair_messages_fn=_build_repair_messages,
        extract_content_fn=_extract_content,
        extract_json_payload_fn=_extract_json_payload,
        validate_court_payload_fn=_validate_court_payload,
        request_factory=urllib.request.Request,
        urlopen_fn=urllib.request.urlopen,
    )


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
    return orchestrator_court_transport.call_model(
        token=token,
        endpoint=endpoint,
        model=model,
        messages=messages,
        fallback_label=fallback_label,
        max_retries=max_retries,
        request_timeout=request_timeout,
        valid_evidence_ids=valid_evidence_ids,
        schema_name=COURT_SCHEMA_NAME,
        response_schema=COURT_RESPONSE_SCHEMA,
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        request_headers_fn=_request_headers,
        extract_content_fn=_extract_content,
        extract_json_payload_fn=_extract_json_payload,
        validate_court_payload_fn=_validate_court_payload,
        attempt_repair_payload_fn=_attempt_repair_payload,
        apply_model_call_interval_fn=apply_model_call_interval,
        compute_retry_delay_fn=compute_retry_delay,
        is_retryable_http_code_fn=is_retryable_http_code,
        register_rate_limit_cooldown_fn=register_rate_limit_cooldown,
        request_factory=urllib.request.Request,
        urlopen_fn=urllib.request.urlopen,
    )


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
    return orchestrator_court_transport.call_with_fallback(
        token=token,
        endpoint=endpoint,
        model=model,
        fallback_model=fallback_model,
        messages=messages,
        fallback_label=fallback_label,
        max_retries=max_retries,
        request_timeout=request_timeout,
        valid_evidence_ids=valid_evidence_ids,
        call_model_fn=_call_model,
    )


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
