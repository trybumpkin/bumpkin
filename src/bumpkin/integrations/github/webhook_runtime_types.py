from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RuntimeWebhookResponse:
    status_code: int
    payload: dict[str, Any]
