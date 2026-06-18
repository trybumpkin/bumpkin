from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


def normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)  # noqa: UP017
    return value.astimezone(timezone.utc)  # noqa: UP017


def to_iso(value: datetime) -> str:
    return normalize_timestamp(value).isoformat()


def from_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return normalize_timestamp(parsed)


def clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def json_dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def require_lastrowid(cursor: sqlite3.Cursor) -> int:
    lastrowid = cursor.lastrowid
    if lastrowid is None:
        raise RuntimeError("SQLite did not return lastrowid for insert operation.")
    return int(lastrowid)


def postgres_row_mapping(row: object) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise TypeError("Expected psycopg row to be mapping-like.")
    return row
