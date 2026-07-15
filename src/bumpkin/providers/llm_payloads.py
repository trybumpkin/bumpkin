from __future__ import annotations

import json
import re
from typing import Any, cast

from bumpkin.json_recovery import iter_json_object_slices

VALID_LABELS = {"MAJOR", "MINOR", "PATCH", "NO_BUMP"}
VALID_CONFIDENCE = {"high", "medium", "low"}
AGGREGATE_CHANGELOG = {
    "MAJOR": "feat: introduce breaking public api changes",
    "MINOR": "feat: add backward-compatible api changes",
    "PATCH": "fix: internal implementation update",
    "NO_BUMP": "chore: no release required",
}
LABEL_KEYS = ("label", "version_bump", "bump", "recommendation")
CONFIDENCE_KEYS = ("confidence", "certainty")
REASONING_KEYS = ("reasoning", "rationale", "reason", "explanation")
CHANGELOG_KEYS = ("changelog", "commit_message", "conventional_commit")
CHANGELOG_PATTERN = re.compile(
    r"^(feat|fix|chore|refactor|perf|docs|build|ci|test|style)(\([^)]+\))?(!)?:\s+\S"
)


class LLMResponseError(RuntimeError):
    pass


def _first_present(payload: dict[str, Any], keys: tuple[str, ...]) -> object | None:
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return value
    return None


def _as_dict(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return cast("dict[str, Any]", value)


def _as_object_list(value: object) -> list[object] | None:
    if not isinstance(value, list):
        return None
    return cast("list[object]", value)


def _repair_unclosed_object(text: str) -> str | None:
    start_idx: int | None = None
    depth = 0
    in_string = False
    escaped = False

    for idx, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            if start_idx is None:
                start_idx = idx
            depth += 1
            continue
        if ch == "}" and depth > 0:
            depth -= 1

    if start_idx is None or depth == 0:
        return None

    candidate = text[start_idx:].strip()
    return candidate + ("}" * depth)


def normalize_label(value: Any) -> str | None:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    mapping = {
        "major": "MAJOR",
        "breaking": "MAJOR",
        "breaking_change": "MAJOR",
        "minor": "MINOR",
        "feature": "MINOR",
        "patch": "PATCH",
        "fix": "PATCH",
        "bugfix": "PATCH",
        "bug_fix": "PATCH",
        "no_bump": "NO_BUMP",
        "nobump": "NO_BUMP",
        "no_release": "NO_BUMP",
        "none": "NO_BUMP",
        "skip": "NO_BUMP",
    }
    if text in mapping:
        return mapping[text]
    candidate = text.upper()
    if candidate in VALID_LABELS:
        return candidate
    return None


def normalize_confidence(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    mapping = {
        "high": "high",
        "medium": "medium",
        "low": "low",
        "strong": "high",
        "moderate": "medium",
        "weak": "low",
    }
    if text in mapping:
        return mapping[text]
    return None


def validate_recommendation(payload: dict[str, Any]) -> dict[str, str]:
    label = str(payload.get("label", "")).strip().upper()
    confidence = str(payload.get("confidence", "")).strip().lower()
    reasoning = str(payload.get("reasoning", "")).strip()
    changelog = str(payload.get("changelog", "")).strip()

    if label not in VALID_LABELS:
        raise LLMResponseError(f"Invalid label in model output: {label!r}")
    if confidence not in VALID_CONFIDENCE:
        raise LLMResponseError(f"Invalid confidence in model output: {confidence!r}")
    if len(reasoning) < 20:
        raise LLMResponseError("Model reasoning is too short; expected at least 20 chars.")
    if not changelog:
        raise LLMResponseError("Model changelog field is empty.")
    if not CHANGELOG_PATTERN.match(changelog):
        raise LLMResponseError("Model changelog must start with one of feat:, fix:, or chore:.")

    return {
        "label": label,
        "confidence": confidence,
        "reasoning": reasoning,
        "changelog": changelog,
    }


def coerce_recommendation_payload(payload: object) -> dict[str, Any]:
    payload_dict = _as_dict(payload)
    if payload_dict is None:
        return {}

    label = normalize_label(_first_present(payload_dict, LABEL_KEYS))
    confidence = normalize_confidence(_first_present(payload_dict, CONFIDENCE_KEYS))
    reasoning = str(_first_present(payload_dict, REASONING_KEYS) or "").strip()
    changelog = str(_first_present(payload_dict, CHANGELOG_KEYS) or "").strip()

    if label and not changelog:
        changelog = AGGREGATE_CHANGELOG.get(label, "chore: no release required")
    if label and len(reasoning) < 20:
        reasoning = (
            f"Model advisory selected {label} after evaluating API-impact signals from the diff."
        )

    coerced = dict(payload_dict)
    if label:
        coerced["label"] = label
    if confidence:
        coerced["confidence"] = confidence
    if reasoning:
        coerced["reasoning"] = reasoning
    if changelog:
        coerced["changelog"] = changelog
    return coerced


def extract_content(response_payload: dict[str, Any]) -> str:
    choices = _as_object_list(response_payload.get("choices"))
    if not choices:
        raise LLMResponseError("Missing choices in model response.")

    first_choice = _as_dict(choices[0])
    if first_choice is None:
        raise LLMResponseError("Missing choices in model response.")
    message = _as_dict(first_choice.get("message")) or {}
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    content_dict = _as_dict(content)
    if content_dict is not None:
        text = content_dict.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    content_list = _as_object_list(content)
    if content_list is not None:
        text_parts: list[str] = []
        for item in content_list:
            item_dict = _as_dict(item)
            if item_dict is None:
                continue
            text = item_dict.get("text")
            if isinstance(text, str) and text.strip():
                text_parts.append(text.strip())
        if text_parts:
            return "\n".join(text_parts).strip()
    tool_calls = _as_object_list(message.get("tool_calls"))
    if tool_calls is not None:
        for tool_call in tool_calls:
            tool_call_dict = _as_dict(tool_call)
            if tool_call_dict is None:
                continue
            function = _as_dict(tool_call_dict.get("function"))
            if function is None:
                continue
            arguments = function.get("arguments")
            if isinstance(arguments, str) and arguments.strip():
                return arguments.strip()
    raise LLMResponseError("Missing message.content in model response.")


def extract_json_payload(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1]).strip()
            if text.startswith("json"):
                text = text[4:].lstrip()

    try:
        parsed = json.loads(text)
        parsed_dict = _as_dict(parsed)
        if parsed_dict is not None:
            return parsed_dict
        if isinstance(parsed, str):
            nested = json.loads(parsed)
            nested_dict = _as_dict(nested)
            if nested_dict is not None:
                return nested_dict
    except json.JSONDecodeError:
        pass

    for candidate in iter_json_object_slices(text):
        try:
            parsed = json.loads(candidate)
            parsed_dict = _as_dict(parsed)
            if parsed_dict is not None:
                return parsed_dict
        except json.JSONDecodeError:
            pass

    repaired = _repair_unclosed_object(text)
    if repaired is not None:
        try:
            parsed = json.loads(repaired)
            parsed_dict = _as_dict(parsed)
            if parsed_dict is not None:
                return parsed_dict
        except json.JSONDecodeError:
            pass

    raise LLMResponseError("Model returned non-JSON output.")
