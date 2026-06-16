from __future__ import annotations

import hmac
import json
from collections.abc import Mapping
from hashlib import sha256

from bumpkin.integrations.github.ingress import (
    OUTCOME_ACCEPTED,
    OUTCOME_DUPLICATE_IGNORED,
    OUTCOME_REJECTED_SIGNATURE,
    OUTCOME_UNSUPPORTED_EVENT,
    OUTCOME_UNSUPPORTED_PROVIDER,
    InMemoryDeliveryStore,
    ingest_webhook_event,
    verify_github_signature,
)
from bumpkin.integrations.github.persistence import SqliteAppStateStore


def _canonical_body(payload: Mapping[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, sha256).hexdigest()


def _headers(*, secret: str, body: bytes, delivery_id: str | None = "delivery-1") -> dict[str, str]:
    headers = {"X-Hub-Signature-256": _signature(secret, body)}
    if delivery_id is not None:
        headers["X-GitHub-Delivery"] = delivery_id
    return headers


def test_verify_github_signature_accepts_valid_signature() -> None:
    body = b'{"hello":"world"}'
    headers = {"X-Hub-Signature-256": _signature("secret", body)}
    verified, reason = verify_github_signature(
        webhook_secret="secret",
        raw_body=body,
        headers=headers,
    )
    assert verified is True
    assert reason is None


def test_verify_github_signature_rejects_invalid_signature() -> None:
    verified, reason = verify_github_signature(
        webhook_secret="secret",
        raw_body=b"{}",
        headers={"X-Hub-Signature-256": "sha256=deadbeef"},
    )
    assert verified is False
    assert reason == "signature_mismatch"


def test_ingest_webhook_event_accepts_and_extracts_slash_command() -> None:
    payload = {
        "action": "created",
        "installation": {"id": 123},
        "repository": {"full_name": "acme/repo"},
        "issue": {"number": 7, "pull_request": {"url": "https://api.github.com/pr/7"}},
        "sender": {"login": "octocat"},
        "comment": {"body": "/bumpkin approve patch"},
    }
    body = _canonical_body(payload)
    result = ingest_webhook_event(
        provider="github",
        event_name="issue_comment",
        payload=payload,
        headers=_headers(secret="secret", body=body),
        webhook_secret="secret",
        delivery_store=InMemoryDeliveryStore(),
        raw_body=body,
    )

    assert result.accepted is True
    assert result.outcome == OUTCOME_ACCEPTED
    assert result.reason is None
    assert result.event is not None
    assert result.event.delivery_id == "delivery-1"
    assert result.command is not None
    assert result.command.name == "approve"
    assert result.command.args == ("patch",)
    assert result.envelope is not None
    assert result.envelope.payload_hash == sha256(body).hexdigest()


def test_ingest_webhook_event_extracts_merge_metadata_without_command() -> None:
    payload = {
        "action": "closed",
        "installation": {"id": 321},
        "repository": {"full_name": "acme/repo"},
        "pull_request": {
            "number": 9,
            "merged": True,
            "merge_commit_sha": "merge-sha-1",
            "base": {"ref": "main", "sha": "base-sha-1"},
            "head": {"ref": "feature/one", "sha": "head-sha-1"},
        },
        "sender": {"login": "maintainer"},
    }
    body = _canonical_body(payload)
    result = ingest_webhook_event(
        provider="github",
        event_name="pull_request",
        payload=payload,
        headers=_headers(secret="secret", body=body, delivery_id="delivery-merge-1"),
        webhook_secret="secret",
        delivery_store=InMemoryDeliveryStore(),
        raw_body=body,
    )

    assert result.accepted is True
    assert result.event is not None
    assert result.event.merged is True
    assert result.event.merge_commit_sha == "merge-sha-1"
    assert result.event.base_ref == "main"
    assert result.event.base_sha == "base-sha-1"
    assert result.event.head_ref == "feature/one"
    assert result.event.head_sha == "head-sha-1"
    assert result.command is None


def test_ingest_webhook_event_rejects_duplicate_delivery() -> None:
    payload = {"repository": {"full_name": "acme/repo"}, "sender": {"login": "octocat"}}
    body = _canonical_body(payload)
    store = InMemoryDeliveryStore()
    first = ingest_webhook_event(
        provider="github",
        event_name="push",
        payload=payload,
        headers=_headers(secret="secret", body=body, delivery_id="dup-1"),
        webhook_secret="secret",
        delivery_store=store,
        raw_body=body,
    )
    second = ingest_webhook_event(
        provider="github",
        event_name="push",
        payload=payload,
        headers=_headers(secret="secret", body=body, delivery_id="dup-1"),
        webhook_secret="secret",
        delivery_store=store,
        raw_body=body,
    )

    assert first.accepted is True
    assert second.accepted is False
    assert second.outcome == OUTCOME_DUPLICATE_IGNORED
    assert second.reason == "duplicate_delivery"
    assert second.envelope is None
    assert second.event is not None


def test_ingest_webhook_event_derives_delivery_id_when_missing_header() -> None:
    payload = {"repository": {"full_name": "acme/repo"}, "sender": {"login": "octocat"}}
    body = _canonical_body(payload)
    headers = _headers(secret="secret", body=body, delivery_id=None)
    first = ingest_webhook_event(
        provider="github",
        event_name="push",
        payload=payload,
        headers=headers,
        webhook_secret="secret",
        delivery_store=InMemoryDeliveryStore(),
        raw_body=body,
    )
    second = ingest_webhook_event(
        provider="github",
        event_name="push",
        payload=payload,
        headers=headers,
        webhook_secret="secret",
        delivery_store=InMemoryDeliveryStore(),
        raw_body=body,
    )

    assert first.event is not None
    assert second.event is not None
    assert first.event.delivery_id is not None
    assert first.event.delivery_id.startswith("derived-")
    assert first.event.delivery_id == second.event.delivery_id


def test_ingest_webhook_event_rejects_invalid_signature() -> None:
    payload = {"repository": {"full_name": "acme/repo"}}
    result = ingest_webhook_event(
        provider="github",
        event_name="push",
        payload=payload,
        headers={"X-Hub-Signature-256": "sha256=invalid"},
        webhook_secret="secret",
        delivery_store=InMemoryDeliveryStore(),
        raw_body=b"{}",
    )

    assert result.accepted is False
    assert result.outcome == OUTCOME_REJECTED_SIGNATURE
    assert result.reason == "signature_mismatch"


def test_ingest_webhook_event_returns_unsupported_event_outcome() -> None:
    payload = {"repository": {"full_name": "acme/repo"}}
    body = _canonical_body(payload)
    result = ingest_webhook_event(
        provider="github",
        event_name="fork",
        payload=payload,
        headers=_headers(secret="secret", body=body, delivery_id="evt-unsupported"),
        webhook_secret="secret",
        delivery_store=InMemoryDeliveryStore(),
        raw_body=body,
    )

    assert result.accepted is False
    assert result.outcome == OUTCOME_UNSUPPORTED_EVENT
    assert result.reason == "unsupported_event_type"


def test_ingest_webhook_event_returns_unsupported_provider_outcome() -> None:
    payload = {"repository": {"full_name": "acme/repo"}}
    result = ingest_webhook_event(
        provider="gitlab",
        event_name="push",
        payload=payload,
        headers={},
        webhook_secret="secret",
        delivery_store=InMemoryDeliveryStore(),
    )

    assert result.accepted is False
    assert result.outcome == OUTCOME_UNSUPPORTED_PROVIDER
    assert result.reason == "unsupported_provider"


def test_ingest_webhook_event_uses_event_store_for_durable_idempotency(tmp_path) -> None:
    payload = {"repository": {"full_name": "acme/repo"}, "sender": {"login": "octocat"}}
    body = _canonical_body(payload)
    headers = _headers(secret="secret", body=body, delivery_id="stable-1")
    store = SqliteAppStateStore(tmp_path / "app.sqlite3")

    first = ingest_webhook_event(
        provider="github",
        event_name="push",
        payload=payload,
        headers=headers,
        webhook_secret="secret",
        delivery_store=InMemoryDeliveryStore(),
        event_store=store,
        raw_body=body,
    )
    second = ingest_webhook_event(
        provider="github",
        event_name="push",
        payload=payload,
        headers=headers,
        webhook_secret="secret",
        delivery_store=InMemoryDeliveryStore(),
        event_store=store,
        raw_body=body,
    )

    assert first.accepted is True
    assert second.accepted is False
    assert second.outcome == OUTCOME_DUPLICATE_IGNORED
    assert store.get_event(provider="github", provider_event_id="stable-1") is not None
    store.close()
