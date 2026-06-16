"""
Example app wiring for framework servers.

Required env vars:
- BUMPKIN_APP_WEBHOOK_SECRET
- BUMPKIN_APP_DB_PATH
"""

from __future__ import annotations

import atexit
import importlib
from typing import Any, cast

from bumpkin.integrations.github.http_adapter import (
    build_asgi_github_webhook_app,
    build_wsgi_github_webhook_app,
)
from bumpkin.integrations.github.webhook import build_app_webhook_service_from_env


def create_fastapi_app() -> Any:
    fastapi_module = importlib.import_module("fastapi")
    fastapi_ctor = cast("Any", fastapi_module).FastAPI

    service = build_app_webhook_service_from_env()
    app = fastapi_ctor()
    app.mount("/webhooks/github", build_asgi_github_webhook_app(service))

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        service.close()

    return app


def create_flask_app() -> Any:
    flask_module = importlib.import_module("flask")
    werkzeug_dispatcher = importlib.import_module("werkzeug.middleware.dispatcher")
    flask_ctor = cast("Any", flask_module).Flask
    dispatcher_ctor = cast("Any", werkzeug_dispatcher).DispatcherMiddleware

    service = build_app_webhook_service_from_env()
    atexit.register(service.close)
    app = flask_ctor(__name__)
    app.wsgi_app = dispatcher_ctor(
        app.wsgi_app,
        {"/webhooks/github": build_wsgi_github_webhook_app(service)},
    )

    return app
