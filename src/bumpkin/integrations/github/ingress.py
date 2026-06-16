from __future__ import annotations

import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Protocol, cast

from bumpkin.integrations.github.commands import parse_slash_command
from bumpkin.integrations.github.events import normalize_webhook_event
from bumpkin.integrations.github.types import AppEvent, SlashCommand

OUTCOME_ACCEPTED = "accepted"
OUTCOME_DUPLICATE_IGNORED = "duplicate_ignored"
OUTCOME_REJECTED_SIGNATURE = "rejected_signature"
OUTCOME_UNSUPPORTED_EVENT = "ignored_unsupported_event"
OUTCOME_UNSUPPORTED_PROVIDER = "unsupported_provider"


@dataclass(frozen=True, slots=True)
class AppEventEnvelope:
    event_id: str
    source: str
    event_type: str
    action: str | None
    received_at: datetime
    headers_hash: str
    payload_hash: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class IngressResult:
    accepted: bool
    outcome: str
    reason: str | None
    envelope: AppEventEnvelope | None
    event: AppEvent | None
    command: SlashCommand | None


class DeliveryStore(Protocol):
    def has(self, source: str, event_id: str) -> bool: ...

    def record(self, source: str, event_id: str) -> None: ...


class EventStore(Protocol):
    def record_event(self, *, envelope: AppEventEnvelope, event: AppEvent) -> bool: ...


class InMemoryDeliveryStore:
    def __init__(self) -> None:
        self._seen: set[tuple[str, str]] = set()

    def has(self, source: str, event_id: str) -> bool:
        key = (source.strip().lower(), event_id.strip())
        return key in self._seen

    def record(self, source: str, event_id: str) -> None:
        key = (source.strip().lower(), event_id.strip())
        self._seen.add(key)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)  # noqa: UP017 - keep basedpyright compatibility


def _as_dict(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return cast("dict[str, Any]", value)


def _normalize_headers(headers: Mapping[str, object]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in headers.items():
        name = str(key).strip().lower()
        if not name:
            continue
        normalized[name] = str(value).strip()
    return normalized


def _canonical_json_bytes(payload: Mapping[str, object]) -> bytes:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return encoded.encode("utf-8")


def _hash_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def _hash_headers(headers: Mapping[str, str]) -> str:
    canonical = "".join(
        f"{key}:{headers[key]}\n" for key in sorted(headers) if key and headers[key]
    )
    return _hash_bytes(canonical.encode("utf-8"))


def _github_delivery_id(
    event_name: str,
    payload: Mapping[str, object],
    headers: Mapping[str, str],
) -> str:
    delivery_id = headers.get("x-github-delivery", "").strip()
    if delivery_id:
        return delivery_id
    fallback_material = (
        f"github:{event_name.strip().lower()}:{_hash_bytes(_canonical_json_bytes(payload))}"
    )
    return f"derived-{_hash_bytes(fallback_material.encode('utf-8'))[:24]}"


def verify_github_signature(
    *,
    webhook_secret: str,
    raw_body: bytes,
    headers: Mapping[str, object],
) -> tuple[bool, str | None]:
    secret = webhook_secret.strip()
    if not secret:
        return False, "missing_webhook_secret"

    normalized_headers = _normalize_headers(headers)
    signature = normalized_headers.get("x-hub-signature-256", "").strip()
    if not signature:
        return False, "missing_signature"
    if not signature.startswith("sha256="):
        return False, "unsupported_signature_format"

    expected = (
        "sha256="
        + hmac.new(
            secret.encode("utf-8"),
            raw_body,
            sha256,
        ).hexdigest()
    )
    if not hmac.compare_digest(signature, expected):
        return False, "signature_mismatch"
    return True, None


def _extract_slash_command(event: AppEvent, payload: Mapping[str, object]) -> SlashCommand | None:
    if event.event != "issue_comment":
        return None
    comment = _as_dict(payload.get("comment"))
    if comment is None:
        return None
    body = str(comment.get("body", "")).strip()
    if not body:
        return None
    return parse_slash_command(body)


def ingest_webhook_event(
    *,
    provider: str,
    event_name: str,
    payload: Mapping[str, object],
    headers: Mapping[str, object],
    webhook_secret: str,
    delivery_store: DeliveryStore,
    event_store: EventStore | None = None,
    raw_body: bytes | None = None,
    received_at: datetime | None = None,
) -> IngressResult:
    normalized_provider = provider.strip().lower()
    if normalized_provider != "github":
        return IngressResult(
            accepted=False,
            outcome=OUTCOME_UNSUPPORTED_PROVIDER,
            reason="unsupported_provider",
            envelope=None,
            event=None,
            command=None,
        )

    payload_bytes = raw_body if raw_body is not None else _canonical_json_bytes(payload)
    signature_ok, signature_error = verify_github_signature(
        webhook_secret=webhook_secret,
        raw_body=payload_bytes,
        headers=headers,
    )
    if not signature_ok:
        return IngressResult(
            accepted=False,
            outcome=OUTCOME_REJECTED_SIGNATURE,
            reason=signature_error,
            envelope=None,
            event=None,
            command=None,
        )

    normalized_headers = _normalize_headers(headers)
    event_id = _github_delivery_id(event_name, payload, normalized_headers)
    event = normalize_webhook_event(
        event_name,
        _as_dict(payload) or {},
        delivery_id=event_id,
    )
    if event is None:
        return IngressResult(
            accepted=False,
            outcome=OUTCOME_UNSUPPORTED_EVENT,
            reason="unsupported_event_type",
            envelope=None,
            event=None,
            command=None,
        )

    if delivery_store.has("github", event_id):
        return IngressResult(
            accepted=False,
            outcome=OUTCOME_DUPLICATE_IGNORED,
            reason="duplicate_delivery",
            envelope=None,
            event=event,
            command=None,
        )

    envelope = AppEventEnvelope(
        event_id=event_id,
        source="github",
        event_type=event.event,
        action=event.action,
        received_at=(received_at or _now_utc()),
        headers_hash=_hash_headers(normalized_headers),
        payload_hash=_hash_bytes(payload_bytes),
        payload=_as_dict(payload) or {},
    )
    if event_store is not None and not event_store.record_event(envelope=envelope, event=event):
        delivery_store.record("github", event_id)
        return IngressResult(
            accepted=False,
            outcome=OUTCOME_DUPLICATE_IGNORED,
            reason="duplicate_delivery",
            envelope=None,
            event=event,
            command=None,
        )

    delivery_store.record("github", event_id)

    return IngressResult(
        accepted=True,
        outcome=OUTCOME_ACCEPTED,
        reason=None,
        envelope=envelope,
        event=event,
        command=_extract_slash_command(event, payload),
    )
