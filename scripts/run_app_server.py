from __future__ import annotations

import os
import sys

from bumpkin.integrations.github.server import run_self_host_server


def _parse_port() -> int:
    raw_port = os.getenv("PORT") or os.getenv("BUMPKIN_APP_PORT") or "8080"
    try:
        port = int(raw_port)
    except ValueError as err:
        raise ValueError("PORT must be an integer.") from err
    if port <= 0:
        raise ValueError("PORT must be a positive integer.")
    return port


def main() -> int:
    host = os.getenv("BUMPKIN_APP_HOST", "0.0.0.0")  # noqa: S104
    try:
        port = _parse_port()
    except ValueError as err:
        print(f"Failed to start app server: {err}", file=sys.stderr)
        return 2

    run_self_host_server(host=host, port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
