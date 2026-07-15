from __future__ import annotations

from datetime import datetime
from typing import Any


def _validate_optional_string(value: object, field: str, errors: list[str]) -> None:
    if value is not None and not isinstance(value, str):
        errors.append(f"{field} must be a string when present.")


def _validate_optional_int(value: object, field: str, errors: list[str]) -> None:
    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        errors.append(f"{field} must be an integer when present.")


def _validate_optional_bool(value: object, field: str, errors: list[str]) -> None:
    if value is not None and not isinstance(value, bool):
        errors.append(f"{field} must be a boolean when present.")


def validate_app_event_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    event = payload.get("event")
    if not isinstance(event, str) or not event.strip():
        errors.append("event is required.")
    for field in (
        "action",
        "repository",
        "sender_login",
        "delivery_id",
        "merge_commit_sha",
        "base_ref",
        "base_sha",
        "head_ref",
        "head_sha",
    ):
        _validate_optional_string(payload.get(field), field, errors)
    _validate_optional_int(payload.get("installation_id"), "installation_id", errors)
    _validate_optional_int(payload.get("pull_request_number"), "pull_request_number", errors)
    _validate_optional_bool(payload.get("merged"), "merged", errors)
    return errors


def validate_slash_command_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append("name is required.")
    args = payload.get("args")
    if not isinstance(args, list):
        errors.append("args is required and must be a list of strings.")
    elif any(not isinstance(arg, str) for arg in args):
        errors.append("args must contain only strings.")
    if not isinstance(payload.get("raw"), str):
        errors.append("raw is required and must be a string.")
    return errors


def validate_app_event_envelope_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in ("event_id", "source", "event_type", "headers_hash", "payload_hash"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field} is required.")
    _validate_optional_string(payload.get("action"), "action", errors)
    timestamp = payload.get("received_at")
    if not isinstance(timestamp, str) or not timestamp.strip():
        errors.append("received_at is required.")
    else:
        try:
            datetime.fromisoformat(timestamp)
        except ValueError:
            errors.append("received_at must be an ISO-8601 timestamp.")
    if not isinstance(payload.get("payload"), dict):
        errors.append("payload is required and must be an object.")
    return errors


def validate_ingress_result_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload.get("accepted"), bool):
        errors.append("accepted is required and must be a boolean.")
    outcome = payload.get("outcome")
    if not isinstance(outcome, str) or not outcome.strip():
        errors.append("outcome is required.")
    _validate_optional_string(payload.get("reason"), "reason", errors)
    nested_validators = (
        ("envelope", validate_app_event_envelope_payload),
        ("event", validate_app_event_payload),
        ("command", validate_slash_command_payload),
    )
    for field, validator in nested_validators:
        nested = payload.get(field)
        if nested is None:
            continue
        if not isinstance(nested, dict):
            errors.append(f"{field} must be an object when present.")
        else:
            errors.extend(validator(nested))
    if payload.get("accepted") is True:
        if payload.get("envelope") is None:
            errors.append("accepted ingress results must include an envelope.")
        if payload.get("event") is None:
            errors.append("accepted ingress results must include an event.")
    return errors


def validate_publish_decision_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload.get("allowed"), bool):
        errors.append("allowed must be a boolean.")
    reasons = payload.get("guard_reasons")
    if not isinstance(reasons, list):
        errors.append("guard_reasons is required and must be a list of strings.")
    elif any(not isinstance(reason, str) or not reason.strip() for reason in reasons):
        errors.append("guard_reasons must contain only non-empty strings.")
    return errors


def validate_approval_record_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in (
        "repository",
        "approved_label",
        "recommendation_hash",
        "approved_by",
        "approved_at",
    ):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field} is required.")
    number = payload.get("pull_request_number")
    if isinstance(number, bool) or not isinstance(number, int):
        errors.append("pull_request_number is required.")
    timestamp = payload.get("approved_at")
    if isinstance(timestamp, str) and timestamp.strip():
        try:
            datetime.fromisoformat(timestamp)
        except ValueError:
            errors.append("approved_at must be an ISO-8601 timestamp.")
    return errors
