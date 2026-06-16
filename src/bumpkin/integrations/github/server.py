from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Protocol, Self, cast
from wsgiref.simple_server import make_server

from bumpkin.integrations.github.http_adapter import StartResponse, build_wsgi_github_webhook_app
from bumpkin.integrations.github.webhook import (
    AppWebhookService,
    build_app_webhook_service_from_env,
)


class WebhookServiceLike(Protocol):
    def handle_github_webhook(
        self,
        *,
        headers: Mapping[str, object],
        raw_body: bytes,
    ) -> Any: ...

    def close(self) -> None: ...


def _json_wsgi_response(
    *,
    start_response: StartResponse,
    status_code: int,
    status_text: str,
    payload: dict[str, Any],
) -> Iterable[bytes]:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    start_response(
        f"{status_code} {status_text}",
        [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
        ],
    )
    return [body]


def build_self_host_wsgi_app(
    service: WebhookServiceLike,
) -> Callable[[Mapping[str, object], StartResponse], Iterable[bytes]]:
    webhook_app = build_wsgi_github_webhook_app(service)

    def app(environ: Mapping[str, object], start_response: StartResponse) -> Iterable[bytes]:
        path = str(environ.get("PATH_INFO", "/")).rstrip("/") or "/"
        if path == "/healthz":
            return _json_wsgi_response(
                start_response=start_response,
                status_code=200,
                status_text="OK",
                payload={"status": "ok"},
            )
        if path == "/webhooks/github":
            return webhook_app(environ, start_response)
        return _json_wsgi_response(
            start_response=start_response,
            status_code=404,
            status_text="NOT FOUND",
            payload={
                "accepted": False,
                "outcome": "not_found",
                "reason": "unknown_path",
            },
        )

    return app


class SelfHostWSGIApp:
    def __init__(self, service: AppWebhookService) -> None:
        self._service = service
        self._app = build_self_host_wsgi_app(service)

    def __call__(
        self,
        environ: Mapping[str, object],
        start_response: StartResponse,
    ) -> Iterable[bytes]:
        return self._app(environ, start_response)

    def close(self) -> None:
        self._service.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


def build_self_host_wsgi_app_from_env(
    environ: Mapping[str, str] | None = None,
) -> SelfHostWSGIApp:
    service = build_app_webhook_service_from_env(environ)
    return SelfHostWSGIApp(service)


def run_self_host_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    environ: Mapping[str, str] | None = None,
) -> None:
    app = build_self_host_wsgi_app_from_env(environ)
    with make_server(host, port, cast("Any", app)) as server:
        try:
            server.serve_forever()
        finally:
            app.close()
