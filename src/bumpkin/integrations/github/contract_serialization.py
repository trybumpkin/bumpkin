from __future__ import annotations

from typing import Any

from bumpkin.integrations.github.guards import ApprovalRecord, PublishGuardDecision
from bumpkin.integrations.github.ingress import AppEventEnvelope, IngressResult
from bumpkin.integrations.github.types import AppEvent, SlashCommand


def slash_command_to_payload(command: SlashCommand) -> dict[str, Any]:
    return {"name": command.name, "args": list(command.args), "raw": command.raw}


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
    return {"allowed": decision.allowed, "guard_reasons": list(decision.guard_reasons)}


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
