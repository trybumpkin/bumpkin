from __future__ import annotations

import io
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from bumpkin.integrations.github.server import build_self_host_wsgi_app
from bumpkin.integrations.github.webhook import WebhookResponse


@dataclass
class _FakeService:
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

    def close(self) -> None:
        return None


def _call_wsgi(
    app: Any,
    environ: Mapping[str, object],
) -> tuple[str, list[tuple[str, str]], bytes]:
    status = ""
    headers: list[tuple[str, str]] = []

    def start_response(value: str, response_headers: list[tuple[str, str]]) -> None:
        nonlocal status, headers
        status = value
        headers = response_headers

    body = b"".join(app(environ, start_response))
    return status, headers, body


def test_self_host_wsgi_app_healthz() -> None:
    app = build_self_host_wsgi_app(_FakeService())
    status, _headers, body = _call_wsgi(
        app,
        {
            "REQUEST_METHOD": "GET",
            "PATH_INFO": "/healthz",
            "CONTENT_LENGTH": "0",
            "wsgi.input": io.BytesIO(b""),
        },
    )
    payload = json.loads(body.decode("utf-8"))

    assert status.startswith("200")
    assert payload["status"] == "ok"


def test_self_host_wsgi_app_routes_webhook_path() -> None:
    service = _FakeService()
    app = build_self_host_wsgi_app(service)
    raw_body = b'{"repository":{"full_name":"acme/repo"}}'
    status, _headers, body = _call_wsgi(
        app,
        {
            "REQUEST_METHOD": "POST",
            "PATH_INFO": "/webhooks/github",
            "CONTENT_LENGTH": str(len(raw_body)),
            "wsgi.input": io.BytesIO(raw_body),
            "HTTP_X_GITHUB_EVENT": "push",
        },
    )
    payload = json.loads(body.decode("utf-8"))

    assert status.startswith("202")
    assert payload["outcome"] == "accepted"
    assert service.calls == 1
    assert service.last_body == raw_body


def test_self_host_wsgi_app_returns_not_found_for_unknown_path() -> None:
    app = build_self_host_wsgi_app(_FakeService())
    status, _headers, body = _call_wsgi(
        app,
        {
            "REQUEST_METHOD": "GET",
            "PATH_INFO": "/unknown",
            "CONTENT_LENGTH": "0",
            "wsgi.input": io.BytesIO(b""),
        },
    )
    payload = json.loads(body.decode("utf-8"))

    assert status.startswith("404")
    assert payload["outcome"] == "not_found"
