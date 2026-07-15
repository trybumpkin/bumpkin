from __future__ import annotations

import random
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any


def is_retryable_http_code(code: int) -> bool:
    return code in {429, 500, 502, 503, 504}


def get_retry_after_seconds(headers: Mapping[str, Any] | Any | None) -> float | None:
    if headers is None:
        return None

    raw_retry_after = None
    if hasattr(headers, "get"):
        raw_retry_after = headers.get("Retry-After") or headers.get("retry-after")
    if raw_retry_after is None and hasattr(headers, "items"):
        for key, value in headers.items():
            if str(key).lower() == "retry-after":
                raw_retry_after = value
                break

    if raw_retry_after is None:
        return None

    text = str(raw_retry_after).strip()
    if not text:
        return None

    if text.isdigit():
        return max(0.0, float(int(text)))

    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None

    now = datetime.now(parsed.tzinfo or UTC)
    delta = (parsed - now).total_seconds()
    return max(0.0, delta)


def compute_retry_delay(
    *,
    attempt_index: int,
    headers: Mapping[str, Any] | Any | None = None,
    base_delays: tuple[float, ...] = (2.0, 4.0, 8.0),
    jitter: float = 0.10,
    max_delay: float = 90.0,
) -> float:
    attempt_index = max(attempt_index, 0)

    base_delay = None
    retry_after = get_retry_after_seconds(headers)
    if retry_after is not None:
        base_delay = retry_after
    else:
        index = max(0, min(attempt_index, len(base_delays) - 1)) if base_delays else 0
        base_delay = base_delays[index] if base_delays else 0.0

    capped_delay = min(base_delay, max_delay)
    jitter_width = capped_delay * jitter
    if jitter_width <= 0:
        return capped_delay

    return max(0.0, capped_delay + random.uniform(-jitter_width, jitter_width))
