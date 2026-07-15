from __future__ import annotations

import json
from collections.abc import Mapping
from hashlib import sha256


def compute_recommendation_hash(payload: Mapping[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()
