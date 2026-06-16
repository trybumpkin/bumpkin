from __future__ import annotations

import asyncio
import io
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from bumpkin.integrations.github.http_adapter import (
    build_asgi_github_webhook_app,
    build_wsgi_github_webhook_app,
)
from bumpkin.integrations.github.webhook import WebhookResponse


@dataclass
class _FakeHandler:
    calls: int = 0
    last_headers: Mapping[str, object] | None = None
    last_body: bytes | None = None
    response: WebhookResponse = field(
        default_factory=lambda: WebhookResponse(
            status_code=202,
            payload={"accepted": True, "outcome": "accepted", "reason": None},
        )
    )

    def handle_github_webhook(
        self,
        *,
        headers: Mapping[str, object],
        raw_body: bytes,
    ) -> WebhookResponse:
        self.calls += 1
        self.last_headers = headers
        self.last_body = raw_body
        return self.response


def test_wsgi_adapter_rejects_non_post() -> None:
    handler = _FakeHandler()
    app = build_wsgi_github_webhook_app(handler)
    start: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        start["status"] = status
        start["headers"] = headers

    body = b"".join(
        app(
            {
                "REQUEST_METHOD": "GET",
                "CONTENT_LENGTH": "0",
                "wsgi.input": io.BytesIO(b""),
            },
            start_response,
        )
    )
    payload = json.loads(body.decode("utf-8"))

    assert start["status"].startswith("405")
    assert payload["reason"] == "method_not_allowed"
    assert handler.calls == 0


def test_wsgi_adapter_passes_headers_and_body_to_handler() -> None:
    handler = _FakeHandler()
    app = build_wsgi_github_webhook_app(handler)
    start: dict[str, Any] = {}
    raw_body = b'{"hello":"world"}'

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        start["status"] = status
        start["headers"] = headers

    body = b"".join(
        app(
            {
                "REQUEST_METHOD": "POST",
                "CONTENT_LENGTH": str(len(raw_body)),
                "CONTENT_TYPE": "application/json",
                "HTTP_X_GITHUB_EVENT": "push",
                "wsgi.input": io.BytesIO(raw_body),
            },
            start_response,
        )
    )
    payload = json.loads(body.decode("utf-8"))

    assert start["status"].startswith("202")
    assert payload["outcome"] == "accepted"
    assert handler.calls == 1
    assert handler.last_body == raw_body
    assert handler.last_headers is not None
    assert handler.last_headers["x-github-event"] == "push"


def test_asgi_adapter_passes_headers_and_body_to_handler() -> None:
    handler = _FakeHandler()
    app = build_asgi_github_webhook_app(handler)
    sent: list[dict[str, Any]] = []
    raw_body = b'{"hello":"world"}'
    scope = {
        "type": "http",
        "method": "POST",
        "headers": [(b"x-github-event", b"push"), (b"content-type", b"application/json")],
    }
    events = [{"type": "http.request", "body": raw_body, "more_body": False}]

    async def receive() -> dict[str, Any]:
        return events.pop(0)

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(app(scope, receive, send))

    assert handler.calls == 1
    assert handler.last_body == raw_body
    assert handler.last_headers is not None
    assert handler.last_headers["x-github-event"] == "push"
    assert sent[0]["status"] == 202
    payload = json.loads(sent[1]["body"].decode("utf-8"))
    assert payload["outcome"] == "accepted"
