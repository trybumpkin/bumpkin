from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from bumpkin.integrations.github.ingress import ingest_webhook_event
from bumpkin.integrations.github.webhook_parsing import _normalize_headers, _status_for_outcome
from bumpkin.integrations.github.webhook_runtime_types import RuntimeWebhookResponse

if TYPE_CHECKING:
    from bumpkin.integrations.github.webhook_runtime import WebhookRuntime

_HEADER_EVENT_NAME = "x-github-event"


class WebhookRequestHandler:
    def __init__(self, runtime: WebhookRuntime) -> None:
        self._runtime = runtime

    def handle(self, *, headers: Mapping[str, object], raw_body: bytes) -> RuntimeWebhookResponse:
        event_name = _event_name(headers)
        if not event_name:
            return _invalid_response("missing_event_name")
        payload_valid, payload = _decode_payload(raw_body)
        if not payload_valid:
            return _invalid_response("invalid_payload_json")
        if not isinstance(payload, dict):
            return _invalid_response("payload_must_be_object")

        result = ingest_webhook_event(
            provider="github",
            event_name=event_name,
            payload=payload,
            headers=headers,
            webhook_secret=self._runtime._config.webhook_secret,
            delivery_store=self._runtime._delivery_store,
            event_store=self._runtime._state_store,
            raw_body=raw_body,
        )
        response_payload: dict[str, Any] = {
            "accepted": result.accepted,
            "outcome": result.outcome,
            "reason": result.reason,
        }
        self._runtime._dispatch_coordinator.dispatch(
            result=result,
            payload=payload,
            response_payload=response_payload,
        )
        return RuntimeWebhookResponse(
            status_code=_status_for_outcome(result.outcome),
            payload=response_payload,
        )


def _event_name(headers: Mapping[str, object]) -> str:
    return _normalize_headers(headers).get(_HEADER_EVENT_NAME, "").strip()


def _decode_payload(raw_body: bytes) -> tuple[bool, object]:
    try:
        return True, json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False, None


def _invalid_response(reason: str) -> RuntimeWebhookResponse:
    return RuntimeWebhookResponse(
        status_code=400,
        payload={"accepted": False, "outcome": "invalid_request", "reason": reason},
    )
