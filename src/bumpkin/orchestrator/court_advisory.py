from __future__ import annotations

from typing import Any


def _skipped_advisory() -> tuple[dict[str, Any], None, None]:
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


def _stub_advisory(engine_label: str) -> tuple[dict[str, Any], None, str]:
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


def _missing_token_advisory() -> tuple[dict[str, Any], str, None]:
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


def _provider_failure_advisory(error: RuntimeError) -> tuple[dict[str, Any], str, None]:
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
        str(error),
        None,
    )


def _finalize_advisory(
    *,
    parsed: dict[str, Any],
    engine_label: str,
    used_model: str,
) -> tuple[dict[str, Any], None, str]:
    if parsed["label"] == engine_label:
        parsed["status"] = "aligned"
        parsed["disagreement_reason"] = None
        return parsed, None, used_model

    parsed["status"] = "manual_review"
    parsed["disagreement_reason"] = (
        f"Court verdict {parsed['label']} disagreed with deterministic decision {engine_label}."
    )
    return parsed, None, used_model


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
    language_hints: list[str] | None,
    build_court_messages_fn: Any,
    extract_case_file_evidence_ids_fn: Any,
    call_with_fallback_fn: Any,
) -> tuple[dict[str, Any], str | None, str | None]:
    if not engine_label:
        return _skipped_advisory()

    if mode.strip().lower() == "stub":
        return _stub_advisory(engine_label)

    if not token:
        return _missing_token_advisory()

    messages = build_court_messages_fn(
        case_file_text=case_file_text,
        engine_label=engine_label,
        language_hints=language_hints,
    )
    valid_evidence_ids = extract_case_file_evidence_ids_fn(case_file_text)
    try:
        parsed, used_model = call_with_fallback_fn(
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
        return _provider_failure_advisory(err)

    return _finalize_advisory(
        parsed=parsed,
        engine_label=engine_label,
        used_model=used_model,
    )
