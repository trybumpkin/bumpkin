from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import pytest

from bumpkin import request_pacing as pacing_module
from bumpkin import retry as retry_module


def test_get_retry_after_seconds_reads_numeric_header() -> None:
    assert retry_module.get_retry_after_seconds({"Retry-After": "14"}) == 14.0
    assert retry_module.get_retry_after_seconds({"retry-after": "14"}) == 14.0


def test_get_retry_after_seconds_parses_http_date() -> None:
    expected_time = datetime.now(UTC) + timedelta(seconds=60)
    header_value = format_datetime(expected_time, usegmt=True)
    parsed = retry_module.get_retry_after_seconds({"Retry-After": header_value})
    assert parsed is not None
    assert 55.0 <= parsed <= 65.0


def test_get_retry_after_seconds_returns_none_for_invalid_value() -> None:
    assert retry_module.get_retry_after_seconds({"Retry-After": "invalid"}) is None


def test_compute_retry_delay_prefers_retry_after_header() -> None:
    delay = retry_module.compute_retry_delay(
        attempt_index=0,
        headers={"Retry-After": "11"},
        jitter=0.0,
    )
    assert delay == 11.0


def test_compute_retry_delay_uses_attempt_backoff_when_header_missing() -> None:
    assert retry_module.compute_retry_delay(attempt_index=0, headers={}, jitter=0.0) == 2.0
    assert retry_module.compute_retry_delay(attempt_index=1, headers=None, jitter=0.0) == 4.0
    assert retry_module.compute_retry_delay(attempt_index=2, headers=None, jitter=0.0) == 8.0


def test_compute_retry_delay_respects_max_delay_cap() -> None:
    delay = retry_module.compute_retry_delay(
        attempt_index=0,
        headers={"Retry-After": "120"},
        jitter=0.0,
        max_delay=90,
    )
    assert delay == 90.0


def test_apply_model_call_interval_honors_zero_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pacing_module.reset_model_request_interval()
    slept: list[float] = []

    def _record_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(pacing_module.time, "sleep", _record_sleep)
    delay = pacing_module.apply_model_call_interval(interval_ms=0)
    assert delay == 0.0
    assert slept == []


def test_apply_model_call_interval_reads_min_ms_and_applies_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pacing_module.reset_model_request_interval()
    slept: list[float] = []
    clock_ticks = [0.0, 0.5, 0.5, 2.0, 2.0]

    def fake_perf_counter() -> float:
        return clock_ticks.pop(0)

    def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(pacing_module.time, "sleep", fake_sleep)
    monkeypatch.setattr(pacing_module.time, "perf_counter", fake_perf_counter)

    assert pacing_module.apply_model_call_interval(interval_ms=1000) == 0.0
    assert pacing_module.apply_model_call_interval(interval_ms=1000) == 0.5
    assert pacing_module.apply_model_call_interval(interval_ms=1000) == 0.0
    assert slept == [0.5]


def test_apply_model_call_interval_uses_default_env_when_interval_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pacing_module.reset_model_request_interval()
    monkeypatch.delenv("BUMPKIN_MODEL_CALL_MIN_INTERVAL_MS", raising=False)

    slept: list[float] = []
    clock_ticks = [0.0, 1.0, 4.0]

    def fake_perf_counter() -> float:
        return clock_ticks.pop(0)

    def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(pacing_module.time, "sleep", fake_sleep)
    monkeypatch.setattr(pacing_module.time, "perf_counter", fake_perf_counter)

    assert pacing_module.apply_model_call_interval() == 0.0
    assert pacing_module.apply_model_call_interval() == 3.0
    assert slept == [3.0]


def test_register_rate_limit_cooldown_is_applied_to_next_model_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pacing_module.reset_model_request_interval()

    slept: list[float] = []
    clock_ticks = [10.0, 10.0, 70.0]

    def fake_perf_counter() -> float:
        return clock_ticks.pop(0)

    def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(pacing_module.time, "sleep", fake_sleep)
    monkeypatch.setattr(pacing_module.time, "perf_counter", fake_perf_counter)

    cooldown = pacing_module.register_rate_limit_cooldown(
        headers={"Retry-After": "5"},
        minimum_seconds=60.0,
    )
    assert cooldown == 60.0
    assert pacing_module.apply_model_call_interval(interval_ms=0) == 60.0
    assert slept == [60.0]
