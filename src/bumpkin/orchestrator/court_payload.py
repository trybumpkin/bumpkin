from __future__ import annotations

import json
import re
from typing import Any, cast

VALID_LABELS = {"MAJOR", "MINOR", "PATCH", "NO_BUMP"}
VALID_CONFIDENCE = {"high", "medium", "low"}

LABEL_PATTERN = re.compile(r"\b(major|minor|patch|no[\s_-]?bump|nobump)\b", re.IGNORECASE)
CONFIDENCE_PATTERN = re.compile(r"\b(high|medium|low|strong|moderate|weak)\b", re.IGNORECASE)
LABEL_KEY_PATTERN = re.compile(r'"\s*label\s*"', re.IGNORECASE)
STRUCTURED_SUMMARY_PATTERN = re.compile(
    r'"\s*(label|confidence|judge_summary|prosecutor_claims|defender_claims)\s*"\s*:',
    re.IGNORECASE,
)
NO_BUMP_HINT_PATTERN = re.compile(
    r"\b(no(?:\s+version)?\s+bump|no[\s_-]?release|docs?[-\s]?only|documentation[-\s]?only)\b",
    re.IGNORECASE,
)
BREAKING_HINT_PATTERN = re.compile(
    r"\b(breaking(?:\s+change)?|backward[-\s]?incompatible|incompatible\s+api)\b",
    re.IGNORECASE,
)
MINOR_HINT_PATTERN = re.compile(
    r"\b(backward[-\s]?compatible|new\s+(?:api|export|endpoint|method|feature)|add(?:ed|s)?\s+(?:api|export|endpoint|method|feature)|feature\s+addition)\b",
    re.IGNORECASE,
)
PATCH_HINT_PATTERN = re.compile(
    r"\b(internal|bug[-\s]?fix|implementation\s+update|refactor|maintenance|non[-\s]?breaking\s+fix|patch\s+level)\b",
    re.IGNORECASE,
)
NO_BREAKING_PATTERN = re.compile(
    r"\b(no|without)\s+breaking\b|\bnon[-\s]?breaking\b", re.IGNORECASE
)


def _as_object_list(value: object) -> list[object] | None:
    if not isinstance(value, list):
        return None
    return cast("list[object]", value)


def _as_dict(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return cast("dict[str, Any]", value)


def _extract_content(response_payload: dict[str, Any]) -> str:
    choices = _as_object_list(response_payload.get("choices", []))
    if not choices:
        raise RuntimeError("Missing choices in model response.")
    first_choice = _as_dict(choices[0]) or {}
    message = _as_dict(first_choice.get("message", {})) or {}
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    content_dict = _as_dict(content)
    if content_dict is not None:
        text = content_dict.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    content_items = _as_object_list(content)
    if content_items is not None:
        # OpenAI-compatible responses can return segmented content blocks.
        text_parts: list[str] = []
        for item in content_items:
            item_dict = _as_dict(item)
            if item_dict is None:
                continue
            text = item_dict.get("text")
            if not isinstance(text, str):
                text = item_dict.get("value")
            if not isinstance(text, str):
                text = item_dict.get("content")
            if isinstance(text, str) and text.strip():
                text_parts.append(text.strip())
        if text_parts:
            return "\n".join(text_parts).strip()
    tool_calls = message.get("tool_calls")
    tool_call_items = _as_object_list(tool_calls)
    if tool_call_items is not None:
        for tool_call in tool_call_items:
            tool_call_dict = _as_dict(tool_call)
            if tool_call_dict is None:
                continue
            function = _as_dict(tool_call_dict.get("function"))
            if function is None:
                continue
            arguments = function.get("arguments")
            if isinstance(arguments, str) and arguments.strip():
                return arguments.strip()
    raise RuntimeError("Missing message.content in model response.")


def _iter_json_object_slices(text: str) -> list[str]:
    candidates: list[str] = []
    for start in (idx for idx, ch in enumerate(text) if ch == "{"):
        depth = 0
        in_string = False
        escaped = False
        for idx in range(start, len(text)):
            ch = text[idx]
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
                depth += 1
                continue
            if ch == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start : idx + 1])
                    break
    return candidates


def _infer_label_from_text(content: str) -> str | None:
    normalized = " ".join(content.split())
    if NO_BUMP_HINT_PATTERN.search(normalized):
        return "NO_BUMP"
    if BREAKING_HINT_PATTERN.search(normalized) and not NO_BREAKING_PATTERN.search(normalized):
        return "MAJOR"
    if MINOR_HINT_PATTERN.search(normalized):
        return "MINOR"
    if PATCH_HINT_PATTERN.search(normalized):
        return "PATCH"
    return None


def _normalize_label(value: Any) -> str | None:
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


def _normalize_confidence(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    mapping = {
        "high": "high",
        "medium": "medium",
        "low": "low",
        "strong": "high",
        "moderate": "medium",
        "weak": "low",
    }
    return mapping.get(text)


def _recover_court_payload_from_text(
    content: str,
    *,
    fallback_label: str | None = None,
) -> dict[str, Any] | None:
    normalized = content.strip()
    if not normalized:
        return None

    label_match = LABEL_PATTERN.search(normalized)
    label = (
        _normalize_label(label_match.group(1))
        if label_match
        else _infer_label_from_text(normalized)
    )
    if not label and fallback_label:
        normalized_fallback = _normalize_label(fallback_label)
        lowered = normalized.lower()
        looks_truncated_structured = normalized.startswith("{") and len(normalized) <= 24
        has_structured_label_hint = LABEL_KEY_PATTERN.search(normalized) or (
            "label" in lowered and ("{" in normalized or ":" in normalized or '"' in normalized)
        )
        if normalized_fallback and (has_structured_label_hint or looks_truncated_structured):
            label = normalized_fallback
    if not label:
        return None

    confidence_match = CONFIDENCE_PATTERN.search(normalized)
    confidence = _normalize_confidence(confidence_match.group(1)) if confidence_match else "low"
    if not confidence:
        confidence = "low"

    summary = " ".join(normalized.split())
    summary = summary[:220].rstrip()
    if len(summary) < 12:
        summary = f"Court selected {label} based on the strongest evidence in the case file."

    return {
        "label": label,
        "confidence": confidence,
        "judge_summary": summary,
        "prosecutor_claims": [],
        "defender_claims": [],
        "accepted_arguments": [],
        "rejected_arguments": [],
        "unresolved_risks": [],
        "accepted_evidence_ids": [],
        "rejected_evidence_ids": [],
    }


def _extract_json_payload(content: str, *, fallback_label: str | None = None) -> dict[str, Any]:
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

    for candidate in _iter_json_object_slices(text):
        try:
            parsed = json.loads(candidate)
            parsed_dict = _as_dict(parsed)
            if parsed_dict is not None:
                return parsed_dict
        except json.JSONDecodeError:
            continue
    recovered = _recover_court_payload_from_text(text, fallback_label=fallback_label)
    if recovered is not None:
        return recovered
    preview = " ".join(text.split())
    if len(preview) > 180:
        preview = preview[:177].rstrip() + "..."
    raise RuntimeError(f"Court returned non-JSON output. content_preview={preview!r}")


def _normalize_string_list(value: object, *, max_items: int = 4, max_chars: int = 180) -> list[str]:
    items = _as_object_list(value)
    if items is None:
        return []
    out: list[str] = []
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        if len(text) > max_chars:
            text = text[: max_chars - 3].rstrip() + "..."
        out.append(text)
        if len(out) >= max_items:
            break
    return out


def _default_judge_summary(label: str) -> str:
    return f"Court selected {label} based on the strongest evidence in the case file."


def _sanitize_judge_summary(judge_summary: str, *, label: str) -> str:
    summary = " ".join(judge_summary.split()).strip()
    if len(summary) < 12:
        return _default_judge_summary(label)
    lowered = summary.lower()
    if STRUCTURED_SUMMARY_PATTERN.search(summary):
        return _default_judge_summary(label)
    if summary.startswith(("{", "[")):
        return _default_judge_summary(label)
    if (
        ("{" in summary or "}" in summary)
        and (":" in summary)
        and ('"' in summary or "'" in summary)
    ):
        return _default_judge_summary(label)
    if lowered.startswith("```") or lowered.endswith("```"):
        return _default_judge_summary(label)
    return summary


def _coerce_court_payload(payload: dict[str, Any]) -> dict[str, Any]:
    label = _normalize_label(
        payload.get("label")
        or payload.get("version_bump")
        or payload.get("bump")
        or payload.get("recommendation")
    )
    confidence = _normalize_confidence(payload.get("confidence") or payload.get("certainty"))
    judge_summary = str(
        payload.get("judge_summary")
        or payload.get("reasoning")
        or payload.get("rationale")
        or payload.get("reason")
        or payload.get("explanation")
        or ""
    ).strip()

    if label:
        judge_summary = _sanitize_judge_summary(judge_summary, label=label)
    if not confidence:
        confidence = "low"

    coerced = dict(payload)
    if label:
        coerced["label"] = label
    if confidence:
        coerced["confidence"] = confidence
    if judge_summary:
        coerced["judge_summary"] = judge_summary
    return coerced


def _extract_case_file_evidence_ids(case_file_text: str) -> set[str]:
    try:
        case_file = json.loads(case_file_text)
    except ValueError:
        return set()
    case_file_dict = _as_dict(case_file)
    if case_file_dict is None:
        return set()
    records = _as_object_list(case_file_dict.get("evidence_records"))
    if records is None:
        return set()
    evidence_ids: set[str] = set()
    for item in records:
        record = _as_dict(item)
        if record is None:
            continue
        evidence_id = str(record.get("evidence_id", "")).strip()
        if evidence_id:
            evidence_ids.add(evidence_id)
    return evidence_ids


def _validate_court_payload(
    payload: dict[str, Any], *, valid_evidence_ids: set[str] | None = None
) -> dict[str, Any]:
    payload = _coerce_court_payload(payload)
    label = str(payload.get("label", "")).strip().upper()
    confidence = str(payload.get("confidence", "")).strip().lower()
    judge_summary = str(payload.get("judge_summary", "")).strip()
    if label not in VALID_LABELS:
        raise RuntimeError(f"Invalid court label: {label!r}")
    if confidence not in VALID_CONFIDENCE:
        raise RuntimeError(f"Invalid court confidence: {confidence!r}")
    if len(judge_summary) < 12:
        raise RuntimeError("Court judge_summary is too short.")
    accepted_evidence_ids = _normalize_string_list(
        payload.get("accepted_evidence_ids"), max_items=6, max_chars=80
    )
    rejected_evidence_ids = _normalize_string_list(
        payload.get("rejected_evidence_ids"), max_items=6, max_chars=80
    )
    if valid_evidence_ids:
        unknown_ids = sorted(
            {
                item
                for item in [*accepted_evidence_ids, *rejected_evidence_ids]
                if item not in valid_evidence_ids
            }
        )
        if unknown_ids:
            raise RuntimeError(f"Court referenced unknown evidence ids: {unknown_ids}")
    return {
        "label": label,
        "confidence": confidence,
        "judge_summary": judge_summary,
        "prosecutor_claims": _normalize_string_list(payload.get("prosecutor_claims"), max_items=4),
        "defender_claims": _normalize_string_list(payload.get("defender_claims"), max_items=4),
        "accepted_arguments": _normalize_string_list(
            payload.get("accepted_arguments"), max_items=4
        ),
        "rejected_arguments": _normalize_string_list(
            payload.get("rejected_arguments"), max_items=4
        ),
        "unresolved_risks": _normalize_string_list(payload.get("unresolved_risks"), max_items=4),
        "accepted_evidence_ids": accepted_evidence_ids,
        "rejected_evidence_ids": rejected_evidence_ids,
    }


extract_case_file_evidence_ids = _extract_case_file_evidence_ids
extract_content = _extract_content
extract_json_payload = _extract_json_payload
iter_json_object_slices = _iter_json_object_slices
normalize_label = _normalize_label
validate_court_payload = _validate_court_payload
