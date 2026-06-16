from __future__ import annotations

from datetime import datetime
from typing import Any

from bumpkin.integrations.github.guards import ApprovalRecord, PublishGuardDecision
from bumpkin.integrations.github.ingress import AppEventEnvelope, IngressResult
from bumpkin.integrations.github.types import AppEvent, SlashCommand


def slash_command_to_payload(command: SlashCommand) -> dict[str, Any]:
    return {
        "name": command.name,
        "args": list(command.args),
        "raw": command.raw,
    }


def app_event_envelope_to_payload(envelope: AppEventEnvelope) -> dict[str, Any]:
    return {
        "event_id": envelope.event_id,
        "source": envelope.source,
        "event_type": envelope.event_type,
        "action": envelope.action,
        "received_at": envelope.received_at.isoformat(),
        "headers_hash": envelope.headers_hash,
        "payload_hash": envelope.payload_hash,
        "payload": dict(envelope.payload),
    }


def app_event_to_payload(event: AppEvent) -> dict[str, Any]:
    return {
        "event": event.event,
        "action": event.action,
        "installation_id": event.installation_id,
        "repository": event.repository,
        "pull_request_number": event.pull_request_number,
        "sender_login": event.sender_login,
        "delivery_id": event.delivery_id,
        "merged": event.merged,
        "merge_commit_sha": event.merge_commit_sha,
        "base_ref": event.base_ref,
        "base_sha": event.base_sha,
        "head_ref": event.head_ref,
        "head_sha": event.head_sha,
    }


def approval_record_to_payload(approval: ApprovalRecord) -> dict[str, Any]:
    return {
        "repository": approval.repository,
        "pull_request_number": approval.pull_request_number,
        "approved_label": approval.approved_label,
        "recommendation_hash": approval.recommendation_hash,
        "approved_by": approval.approved_by,
        "approved_at": approval.approved_at.isoformat(),
    }


def publish_guard_decision_to_payload(decision: PublishGuardDecision) -> dict[str, Any]:
    return {
        "allowed": decision.allowed,
        "guard_reasons": list(decision.guard_reasons),
    }


def ingress_result_to_payload(result: IngressResult) -> dict[str, Any]:
    return {
        "accepted": result.accepted,
        "outcome": result.outcome,
        "reason": result.reason,
        "envelope": app_event_envelope_to_payload(result.envelope)
        if result.envelope is not None
        else None,
        "event": app_event_to_payload(result.event) if result.event is not None else None,
        "command": slash_command_to_payload(result.command) if result.command is not None else None,
    }


def _validate_optional_string(value: object, field: str, errors: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        errors.append(f"{field} must be a string when present.")


def _validate_optional_int(value: object, field: str, errors: list[str]) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        errors.append(f"{field} must be an integer when present.")


def _validate_optional_bool(value: object, field: str, errors: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, bool):
        errors.append(f"{field} must be a boolean when present.")


def validate_app_event_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    event = payload.get("event")
    if not isinstance(event, str) or not event.strip():
        errors.append("event is required.")
    _validate_optional_string(payload.get("action"), "action", errors)
    _validate_optional_int(payload.get("installation_id"), "installation_id", errors)
    _validate_optional_string(payload.get("repository"), "repository", errors)
    _validate_optional_int(payload.get("pull_request_number"), "pull_request_number", errors)
    _validate_optional_string(payload.get("sender_login"), "sender_login", errors)
    _validate_optional_string(payload.get("delivery_id"), "delivery_id", errors)
    _validate_optional_bool(payload.get("merged"), "merged", errors)
    _validate_optional_string(payload.get("merge_commit_sha"), "merge_commit_sha", errors)
    _validate_optional_string(payload.get("base_ref"), "base_ref", errors)
    _validate_optional_string(payload.get("base_sha"), "base_sha", errors)
    _validate_optional_string(payload.get("head_ref"), "head_ref", errors)
    _validate_optional_string(payload.get("head_sha"), "head_sha", errors)
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
    raw = payload.get("raw")
    if not isinstance(raw, str):
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
        normalized = timestamp.replace("Z", "+00:00")
        try:
            datetime.fromisoformat(normalized)
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

    envelope_payload = payload.get("envelope")
    if envelope_payload is not None:
        if not isinstance(envelope_payload, dict):
            errors.append("envelope must be an object when present.")
        else:
            errors.extend(validate_app_event_envelope_payload(envelope_payload))

    event_payload = payload.get("event")
    if event_payload is not None:
        if not isinstance(event_payload, dict):
            errors.append("event must be an object when present.")
        else:
            errors.extend(validate_app_event_payload(event_payload))

    command_payload = payload.get("command")
    if command_payload is not None:
        if not isinstance(command_payload, dict):
            errors.append("command must be an object when present.")
        else:
            errors.extend(validate_slash_command_payload(command_payload))

    if payload.get("accepted") is True and envelope_payload is None:
        errors.append("accepted ingress results must include an envelope.")
    if payload.get("accepted") is True and event_payload is None:
        errors.append("accepted ingress results must include an event.")
    return errors


def validate_publish_decision_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    allowed = payload.get("allowed")
    if not isinstance(allowed, bool):
        errors.append("allowed must be a boolean.")
    guard_reasons = payload.get("guard_reasons")
    if not isinstance(guard_reasons, list):
        errors.append("guard_reasons is required and must be a list of strings.")
    elif any(not isinstance(reason, str) or not reason.strip() for reason in guard_reasons):
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
    pull_request_number = payload.get("pull_request_number")
    if isinstance(pull_request_number, bool) or not isinstance(pull_request_number, int):
        errors.append("pull_request_number is required.")

    timestamp = payload.get("approved_at")
    if isinstance(timestamp, str) and timestamp.strip():
        normalized = timestamp.replace("Z", "+00:00")
        try:
            datetime.fromisoformat(normalized)
        except ValueError:
            errors.append("approved_at must be an ISO-8601 timestamp.")
    return errors
