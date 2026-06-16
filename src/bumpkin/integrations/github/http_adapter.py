from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Coroutine, Iterable, Mapping
from typing import Any, Protocol, cast

from bumpkin.integrations.github.webhook import WebhookResponse

JsonDict = dict[str, Any]
StartResponse = Callable[[str, list[tuple[str, str]]], None]


class WebhookHandler(Protocol):
    def handle_github_webhook(
        self,
        *,
        headers: Mapping[str, object],
        raw_body: bytes,
    ) -> WebhookResponse: ...


def _json_response(status_code: int, payload: JsonDict) -> WebhookResponse:
    return WebhookResponse(status_code=status_code, payload=payload)


def _serialize_response(response: WebhookResponse) -> tuple[int, bytes]:
    body = json.dumps(response.payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return response.status_code, body


def _method_not_allowed() -> WebhookResponse:
    return _json_response(
        405,
        {
            "accepted": False,
            "outcome": "invalid_request",
            "reason": "method_not_allowed",
        },
    )


def _normalize_wsgi_headers(environ: Mapping[str, object]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in environ.items():
        if not key.startswith("HTTP_"):
            continue
        name = key[5:].replace("_", "-").lower()
        headers[name] = str(value)
    if "CONTENT_TYPE" in environ:
        headers["content-type"] = str(environ["CONTENT_TYPE"])
    return headers


def build_wsgi_github_webhook_app(
    handler: WebhookHandler,
) -> Callable[[Mapping[str, object], StartResponse], Iterable[bytes]]:
    def app(environ: Mapping[str, object], start_response: StartResponse) -> Iterable[bytes]:
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        if method != "POST":
            status_code, body = _serialize_response(_method_not_allowed())
            start_response(
                f"{status_code} METHOD NOT ALLOWED",
                [
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(len(body))),
                ],
            )
            return [body]

        raw_length = str(environ.get("CONTENT_LENGTH", "0")).strip()
        content_length = int(raw_length) if raw_length.isdigit() else 0
        input_stream = cast("Any", environ.get("wsgi.input"))
        raw_body = bytes(input_stream.read(content_length) if input_stream is not None else b"")

        response = handler.handle_github_webhook(
            headers=_normalize_wsgi_headers(environ),
            raw_body=raw_body,
        )
        status_code, body = _serialize_response(response)
        start_response(
            f"{status_code} OK",
            [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(body))),
            ],
        )
        return [body]

    return app


def _normalize_asgi_headers(raw_headers: list[tuple[bytes, bytes]]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in raw_headers:
        normalized[key.decode("latin-1").lower()] = value.decode("latin-1")
    return normalized


def build_asgi_github_webhook_app(
    handler: WebhookHandler,
) -> Callable[
    [
        dict[str, Any],
        Callable[[], Awaitable[dict[str, Any]]],
        Callable[[dict[str, Any]], Awaitable[None]],
    ],
    Coroutine[Any, Any, None],
]:
    async def app(
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http":
            response = _json_response(
                500,
                {
                    "accepted": False,
                    "outcome": "internal_error",
                    "reason": "unsupported_scope",
                },
            )
        elif str(scope.get("method", "GET")).upper() != "POST":
            response = _method_not_allowed()
        else:
            body_chunks: list[bytes] = []
            while True:
                event = await receive()
                body_chunks.append(bytes(event.get("body", b"")))
                if not event.get("more_body", False):
                    break
            response = handler.handle_github_webhook(
                headers=_normalize_asgi_headers(list(scope.get("headers", []))),
                raw_body=b"".join(body_chunks),
            )

        status_code, body = _serialize_response(response)
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": body,
            }
        )

    return app
