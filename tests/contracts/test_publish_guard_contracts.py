from __future__ import annotations

from bumpkin.integrations.github.contracts import (
    publish_guard_decision_to_payload,
    validate_publish_decision_payload,
)
from bumpkin.integrations.github.guards import PublishGuardDecision


def test_publish_decision_contract_requires_guard_reasons() -> None:
    errors = validate_publish_decision_payload({"allowed": False})
    assert "guard_reasons is required and must be a list of strings." in errors


def test_publish_decision_contract_requires_boolean_allowed() -> None:
    errors = validate_publish_decision_payload({"allowed": "yes", "guard_reasons": []})
    assert "allowed must be a boolean." in errors


def test_publish_decision_payload_round_trip() -> None:
    decision = PublishGuardDecision(
        allowed=False,
        guard_reasons=("stale_approval", "required_checks_not_green"),
    )
    payload = publish_guard_decision_to_payload(decision)

    assert validate_publish_decision_payload(payload) == []
    assert payload == {
        "allowed": False,
        "guard_reasons": ["stale_approval", "required_checks_not_green"],
    }
