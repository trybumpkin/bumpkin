from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class EvaluationRun:
    results: list[Any]
    passed_count: int
    pass_rate: float
    avg_latency_ms: float
    avg_tokens: float
    metrics: dict[str, Any]
    preflight: dict[str, Any]
    mode_used: str
