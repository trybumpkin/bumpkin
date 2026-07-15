from __future__ import annotations

import os
import threading
import time
from collections.abc import Mapping
from typing import Any

from bumpkin.retry import get_retry_after_seconds

_request_interval_state = threading.Lock()
_last_model_request_ns: float | None = None
_rate_limit_cooldown_until_ns: float | None = None


def _read_model_interval_ms() -> int:
    raw = os.getenv("BUMPKIN_MODEL_CALL_MIN_INTERVAL_MS", "4000").strip()
    try:
        value = int(raw)
    except ValueError:
        return 0
    return max(0, value)


def apply_model_call_interval(*, interval_ms: int | None = None) -> float:
    """Rate-limit model API requests by waiting before each outbound call.

    Returns the number of seconds slept for callers that want observability.
    """
    effective_interval_ms = (
        int(interval_ms) if interval_ms is not None else _read_model_interval_ms()
    )
    effective_interval_seconds = max(0.0, effective_interval_ms / 1000.0)
    with _request_interval_state:
        global _last_model_request_ns
        total_sleep_seconds = 0.0
        now = time.perf_counter()
        if _rate_limit_cooldown_until_ns is not None and now < _rate_limit_cooldown_until_ns:
            cooldown_sleep = _rate_limit_cooldown_until_ns - now
            time.sleep(cooldown_sleep)
            total_sleep_seconds += cooldown_sleep
            now = time.perf_counter()

        if effective_interval_seconds <= 0:
            _last_model_request_ns = now
            return total_sleep_seconds

        if _last_model_request_ns is None:
            _last_model_request_ns = now
            return total_sleep_seconds

        delta = now - _last_model_request_ns
        interval_sleep = max(0.0, effective_interval_seconds - delta)
        if interval_sleep > 0:
            time.sleep(interval_sleep)
            total_sleep_seconds += interval_sleep
        _last_model_request_ns = time.perf_counter()
        return total_sleep_seconds


def register_rate_limit_cooldown(
    *,
    headers: Mapping[str, Any] | Any | None = None,
    minimum_seconds: float = 60.0,
) -> float:
    """Broadcast provider cooldown across subsequent model calls in this process."""
    cooldown_seconds = get_retry_after_seconds(headers)
    if cooldown_seconds is None:
        cooldown_seconds = max(0.0, float(minimum_seconds))
    else:
        cooldown_seconds = max(cooldown_seconds, float(minimum_seconds))

    with _request_interval_state:
        global _rate_limit_cooldown_until_ns
        now = time.perf_counter()
        candidate = now + cooldown_seconds
        if _rate_limit_cooldown_until_ns is None:
            _rate_limit_cooldown_until_ns = candidate
        else:
            _rate_limit_cooldown_until_ns = max(_rate_limit_cooldown_until_ns, candidate)
    return cooldown_seconds


def reset_model_request_interval() -> None:
    """Test helper to reset interval state for deterministic call pacing assertions."""
    global _last_model_request_ns
    global _rate_limit_cooldown_until_ns
    with _request_interval_state:
        _last_model_request_ns = None
        _rate_limit_cooldown_until_ns = None
