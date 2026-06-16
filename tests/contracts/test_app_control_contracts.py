from __future__ import annotations

from datetime import UTC, datetime

from bumpkin.integrations.github.contracts import (
    app_event_envelope_to_payload,
    app_event_to_payload,
    approval_record_to_payload,
    ingress_result_to_payload,
    slash_command_to_payload,
    validate_app_event_envelope_payload,
    validate_app_event_payload,
    validate_approval_record_payload,
    validate_ingress_result_payload,
)
from bumpkin.integrations.github.guards import ApprovalRecord
from bumpkin.integrations.github.ingress import AppEventEnvelope, IngressResult
from bumpkin.integrations.github.types import AppEvent, SlashCommand


def test_app_event_payload_contract_round_trip() -> None:
    event = AppEvent(
        event="pull_request",
        action="closed",
        installation_id=123,
        repository="acme/repo",
        pull_request_number=7,
        sender_login="octocat",
        delivery_id="delivery-1",
        merged=True,
        merge_commit_sha="abc123",
        base_ref="main",
        base_sha="base-sha",
        head_ref="feature",
        head_sha="head-sha",
    )
    payload = app_event_to_payload(event)

    assert validate_app_event_payload(payload) == []
    assert payload["event"] == "pull_request"
    assert payload["pull_request_number"] == 7
    assert payload["merged"] is True
    assert payload["merge_commit_sha"] == "abc123"
    assert payload["base_ref"] == "main"
    assert payload["head_ref"] == "feature"


def test_slash_command_payload_contract() -> None:
    command = SlashCommand(name="approve", args=("patch",), raw="/bumpkin approve patch")
    payload = slash_command_to_payload(command)

    assert payload == {
        "name": "approve",
        "args": ["patch"],
        "raw": "/bumpkin approve patch",
    }


def test_approval_record_payload_contract_round_trip() -> None:
    approval = ApprovalRecord(
        repository="acme/repo",
        pull_request_number=44,
        approved_label="MINOR",
        recommendation_hash="hash-44",
        approved_by="maintainer",
        approved_at=datetime(2026, 3, 19, 10, 30, tzinfo=UTC),
    )
    payload = approval_record_to_payload(approval)

    assert validate_approval_record_payload(payload) == []
    assert payload["pull_request_number"] == 44
    assert payload["approved_label"] == "MINOR"


def test_app_event_envelope_payload_contract_round_trip() -> None:
    envelope = AppEventEnvelope(
        event_id="delivery-1",
        source="github",
        event_type="issue_comment",
        action="created",
        received_at=datetime(2026, 3, 19, 10, 30, tzinfo=UTC),
        headers_hash="headers-hash",
        payload_hash="payload-hash",
        payload={"comment": {"body": "/bumpkin approve"}},
    )
    payload = app_event_envelope_to_payload(envelope)

    assert validate_app_event_envelope_payload(payload) == []
    assert payload["event_id"] == "delivery-1"
    assert payload["event_type"] == "issue_comment"


def test_ingress_result_payload_contract_round_trip() -> None:
    event = AppEvent(
        event="issue_comment",
        action="created",
        installation_id=123,
        repository="acme/repo",
        pull_request_number=7,
        sender_login="octocat",
        delivery_id="delivery-1",
    )
    envelope = AppEventEnvelope(
        event_id="delivery-1",
        source="github",
        event_type="issue_comment",
        action="created",
        received_at=datetime(2026, 3, 19, 10, 30, tzinfo=UTC),
        headers_hash="headers-hash",
        payload_hash="payload-hash",
        payload={"comment": {"body": "/bumpkin approve"}},
    )
    result = IngressResult(
        accepted=True,
        outcome="accepted",
        reason=None,
        envelope=envelope,
        event=event,
        command=SlashCommand(name="approve", args=("patch",), raw="/bumpkin approve patch"),
    )
    payload = ingress_result_to_payload(result)

    assert validate_ingress_result_payload(payload) == []
    assert payload["accepted"] is True
    assert payload["envelope"]["source"] == "github"
    assert payload["command"]["name"] == "approve"


def test_app_event_payload_contract_rejects_invalid_merge_flag_type() -> None:
    payload = {
        "event": "pull_request",
        "action": "closed",
        "installation_id": 123,
        "repository": "acme/repo",
        "pull_request_number": 7,
        "sender_login": "octocat",
        "delivery_id": "delivery-1",
        "merged": "true",
        "merge_commit_sha": "abc123",
        "base_ref": "main",
        "base_sha": "base-sha",
        "head_ref": "feature",
        "head_sha": "head-sha",
    }

    errors = validate_app_event_payload(payload)
    assert "merged must be a boolean when present." in errors


def test_ingress_result_payload_contract_requires_envelope_when_accepted() -> None:
    payload = {
        "accepted": True,
        "outcome": "accepted",
        "reason": None,
        "envelope": None,
        "event": {
            "event": "push",
            "action": None,
            "installation_id": None,
            "repository": "acme/repo",
            "pull_request_number": None,
            "sender_login": None,
            "delivery_id": "delivery-1",
        },
        "command": None,
    }
    errors = validate_ingress_result_payload(payload)
    assert "accepted ingress results must include an envelope." in errors
