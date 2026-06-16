from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Any, cast

from bumpkin.io.tokens import is_github_models_endpoint
from bumpkin.retry import (
    apply_model_call_interval,
    compute_retry_delay,
    is_retryable_http_code,
    register_rate_limit_cooldown,
)

VALID_LABELS = {"MAJOR", "MINOR", "PATCH", "NO_BUMP"}
VALID_CONFIDENCE = {"high", "medium", "low"}
DEFAULT_MAX_OUTPUT_TOKENS = 400
REPAIR_MAX_OUTPUT_TOKENS = 260
COURT_SCHEMA_NAME = "compatibility_court_verdict_v1"
COURT_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "label": {"type": "string", "enum": ["MAJOR", "MINOR", "PATCH", "NO_BUMP"]},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "judge_summary": {"type": "string", "minLength": 12},
        "prosecutor_claims": {"type": "array", "items": {"type": "string"}},
        "defender_claims": {"type": "array", "items": {"type": "string"}},
        "accepted_arguments": {"type": "array", "items": {"type": "string"}},
        "rejected_arguments": {"type": "array", "items": {"type": "string"}},
        "unresolved_risks": {"type": "array", "items": {"type": "string"}},
        "accepted_evidence_ids": {"type": "array", "items": {"type": "string"}},
        "rejected_evidence_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "label",
        "confidence",
        "judge_summary",
        "prosecutor_claims",
        "defender_claims",
        "accepted_arguments",
        "rejected_arguments",
        "unresolved_risks",
        "accepted_evidence_ids",
        "rejected_evidence_ids",
    ],
}
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


def _request_headers(token: str, endpoint: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if is_github_models_endpoint(endpoint):
        headers["Accept"] = "application/vnd.github+json"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    return headers


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


def request_headers(token: str, endpoint: str) -> dict[str, str]:
    return _request_headers(token, endpoint)


def extract_content(response_payload: dict[str, Any]) -> str:
    return _extract_content(response_payload)


def iter_json_object_slices(text: str) -> list[str]:
    return _iter_json_object_slices(text)


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


def build_court_messages(
    *,
    case_file_text: str,
    engine_label: str,
    language_hints: list[str] | None = None,
) -> list[dict[str, str]]:
    system = (
        "You are Compatibility Court. Reason over the provided case file and return strict JSON only. "
        "Required keys: label, confidence, judge_summary, prosecutor_claims, defender_claims, "
        "accepted_arguments, rejected_arguments, unresolved_risks, accepted_evidence_ids, "
        "rejected_evidence_ids. "
        "label must be MAJOR|MINOR|PATCH|NO_BUMP. confidence must be high|medium|low. "
        "Every accepted/rejected evidence id must exist in case_file.evidence_records[]. "
        "Each claim should cite those IDs or file paths present in the case file. "
        "Do not include markdown."
    )
    user = (
        "Court protocol:\n"
        "1) Prosecutor argues for higher-impact bump from evidence.\n"
        "2) Defender argues for lower-impact bump from evidence.\n"
        "3) Judge issues final verdict with accepted/rejected arguments and unresolved risks.\n\n"
        f"Deterministic engine label: {engine_label}\n\n"
        + (
            "Language-specific API hints:\n"
            + "".join(f"- {hint}\n" for hint in language_hints)
            + "\n"
            if language_hints
            else ""
        )
        + "Case file:\n"
        + f"{case_file_text}\n"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _build_repair_messages(*, raw_output: str, fallback_label: str | None) -> list[dict[str, str]]:
    default_label = _normalize_label(fallback_label or "") or "PATCH"
    system = (
        "You repair malformed Compatibility Court output into strict JSON only. "
        "Return one JSON object with keys: label, confidence, judge_summary, "
        "prosecutor_claims, defender_claims, accepted_arguments, rejected_arguments, unresolved_risks, "
        "accepted_evidence_ids, rejected_evidence_ids. "
        "label must be MAJOR|MINOR|PATCH|NO_BUMP. confidence must be high|medium|low. "
        "No markdown, no prose."
    )
    user = (
        "Repair the malformed payload below.\n"
        f"If label is missing or truncated, use default label {default_label}.\n"
        "If confidence is missing, use low.\n"
        "If judge_summary is missing, provide one concise sentence.\n\n"
        "Malformed output:\n"
        f"{raw_output[:1500]}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _attempt_repair_payload(
    *,
    token: str,
    endpoint: str,
    model: str,
    raw_output: str,
    fallback_label: str | None,
    valid_evidence_ids: set[str] | None,
    request_timeout: int,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": _build_repair_messages(raw_output=raw_output, fallback_label=fallback_label),
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": COURT_SCHEMA_NAME,
                "strict": True,
                "schema": COURT_RESPONSE_SCHEMA,
            },
        },
        "temperature": 0,
        "max_tokens": REPAIR_MAX_OUTPUT_TOKENS,
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers=_request_headers(token, endpoint),
    )
    try:
        with urllib.request.urlopen(req, timeout=max(1, request_timeout)) as response:
            raw = json.loads(response.read().decode("utf-8"))
        return _validate_court_payload(
            _extract_json_payload(_extract_content(raw), fallback_label=fallback_label),
            valid_evidence_ids=valid_evidence_ids,
        )
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"repair_http_{err.code}: {body[:180]}") from err
    except urllib.error.URLError as err:
        raise RuntimeError(f"repair_url_error: {err.reason}") from err
    except TimeoutError as err:
        raise RuntimeError(str(err) or "repair request timed out") from err
    except (ValueError, RuntimeError) as err:
        raise RuntimeError(f"repair_parse_error: {err}") from err


def _call_model(
    *,
    token: str,
    endpoint: str,
    model: str,
    messages: list[dict[str, str]],
    fallback_label: str | None,
    max_retries: int,
    request_timeout: int,
    valid_evidence_ids: set[str] | None = None,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": messages,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": COURT_SCHEMA_NAME,
                "strict": True,
                "schema": COURT_RESPONSE_SCHEMA,
            },
        },
        "temperature": 0,
        "max_tokens": DEFAULT_MAX_OUTPUT_TOKENS,
    }
    attempts = max(1, max_retries)
    retry_delays: list[float] = []
    last_error = "unknown"
    for attempt in range(attempts):
        apply_model_call_interval()
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers=_request_headers(token, endpoint),
        )
        try:
            with urllib.request.urlopen(req, timeout=max(1, request_timeout)) as response:
                raw = json.loads(response.read().decode("utf-8"))
            try:
                return _validate_court_payload(
                    _extract_json_payload(_extract_content(raw), fallback_label=fallback_label),
                    valid_evidence_ids=valid_evidence_ids,
                )
            except (ValueError, RuntimeError) as parse_err:
                raw_snapshot = json.dumps(raw, ensure_ascii=True)
                try:
                    return _attempt_repair_payload(
                        token=token,
                        endpoint=endpoint,
                        model=model,
                        raw_output=raw_snapshot,
                        fallback_label=fallback_label,
                        valid_evidence_ids=valid_evidence_ids,
                        request_timeout=request_timeout,
                    )
                except RuntimeError as repair_err:
                    raise RuntimeError(f"{parse_err}; repair_failed={repair_err}") from repair_err
        except urllib.error.HTTPError as err:
            body = err.read().decode("utf-8", errors="replace")
            last_error = f"HTTP {err.code}: {body[:280]}"
            if is_retryable_http_code(err.code) and attempt < attempts - 1:
                base_delays = (60.0, 90.0, 90.0) if err.code == 429 else (2.0, 4.0, 8.0)
                if err.code == 429:
                    register_rate_limit_cooldown(headers=err.headers, minimum_seconds=60.0)
                delay = compute_retry_delay(
                    attempt_index=attempt,
                    headers=err.headers,
                    base_delays=base_delays,
                )
                retry_delays.append(delay)
                time.sleep(delay)
                continue
            if retry_delays:
                last_error += f" retry_delays={retry_delays}"
            raise RuntimeError(last_error) from err
        except urllib.error.URLError as err:
            last_error = str(err.reason)
            if attempt < attempts - 1:
                delay = compute_retry_delay(attempt_index=attempt)
                retry_delays.append(delay)
                time.sleep(delay)
                continue
            if retry_delays:
                last_error += f" retry_delays={retry_delays}"
            raise RuntimeError(last_error) from err
        except TimeoutError as err:
            last_error = str(err) or "request timed out"
            if attempt < attempts - 1:
                delay = compute_retry_delay(attempt_index=attempt)
                retry_delays.append(delay)
                time.sleep(delay)
                continue
            if retry_delays:
                last_error += f" retry_delays={retry_delays}"
            raise RuntimeError(last_error) from err
        except (ValueError, RuntimeError) as err:
            last_error = str(err)
            if attempt < attempts - 1:
                delay = compute_retry_delay(attempt_index=attempt)
                retry_delays.append(delay)
                time.sleep(delay)
                continue
            if retry_delays:
                last_error += f" retry_delays={retry_delays}"
            raise RuntimeError(last_error) from err
    raise RuntimeError(last_error)


def _call_with_fallback(
    *,
    token: str,
    endpoint: str,
    model: str,
    fallback_model: str | None,
    messages: list[dict[str, str]],
    fallback_label: str | None,
    max_retries: int,
    request_timeout: int,
    valid_evidence_ids: set[str] | None = None,
) -> tuple[dict[str, Any], str]:
    try:
        return (
            _call_model(
                token=token,
                endpoint=endpoint,
                model=model,
                messages=messages,
                fallback_label=fallback_label,
                valid_evidence_ids=valid_evidence_ids,
                max_retries=max_retries,
                request_timeout=request_timeout,
            ),
            model,
        )
    except RuntimeError as primary_err:
        candidate = (fallback_model or "").strip()
        if not candidate or candidate == model:
            raise RuntimeError(str(primary_err)) from primary_err
        try:
            return (
                _call_model(
                    token=token,
                    endpoint=endpoint,
                    model=candidate,
                    messages=messages,
                    fallback_label=fallback_label,
                    valid_evidence_ids=valid_evidence_ids,
                    max_retries=max_retries,
                    request_timeout=request_timeout,
                ),
                candidate,
            )
        except RuntimeError as fallback_err:
            raise RuntimeError(
                f"Primary model failed: {primary_err}. Fallback model failed: {fallback_err}."
            ) from fallback_err


def run_court_advisory(
    *,
    mode: str,
    model: str,
    fallback_model: str | None,
    endpoint: str,
    token: str,
    max_retries: int,
    request_timeout: int,
    engine_label: str | None,
    case_file_text: str,
    language_hints: list[str] | None = None,
) -> tuple[dict[str, Any], str | None, str | None]:
    if not engine_label:
        return (
            {
                "status": "skipped",
                "label": None,
                "confidence": None,
                "judge_summary": "Court advisory skipped because no deterministic classification was available.",
                "prosecutor_claims": [],
                "defender_claims": [],
                "accepted_arguments": [],
                "rejected_arguments": [],
                "unresolved_risks": [],
                "accepted_evidence_ids": [],
                "rejected_evidence_ids": [],
                "disagreement_reason": None,
            },
            None,
            None,
        )

    normalized_mode = mode.strip().lower()
    if normalized_mode == "stub":
        return (
            {
                "status": "aligned",
                "label": engine_label,
                "confidence": "high",
                "judge_summary": "Stub court advisory mirrors deterministic decision.",
                "prosecutor_claims": [
                    "Stub prosecutor: deterministic evidence indicates the selected impact."
                ],
                "defender_claims": ["Stub defender: no contradictory evidence in stub mode."],
                "accepted_arguments": ["Deterministic evidence chain is accepted in stub mode."],
                "rejected_arguments": [],
                "unresolved_risks": [],
                "accepted_evidence_ids": [],
                "rejected_evidence_ids": [],
                "disagreement_reason": None,
            },
            None,
            "stub",
        )

    if not token:
        return (
            {
                "status": "degraded",
                "label": None,
                "confidence": None,
                "judge_summary": "Court advisory degraded because no model token was available.",
                "prosecutor_claims": [],
                "defender_claims": [],
                "accepted_arguments": [],
                "rejected_arguments": [],
                "unresolved_risks": [],
                "accepted_evidence_ids": [],
                "rejected_evidence_ids": [],
                "disagreement_reason": None,
            },
            "missing_model_token",
            None,
        )

    messages = build_court_messages(
        case_file_text=case_file_text,
        engine_label=engine_label,
        language_hints=language_hints,
    )
    valid_evidence_ids = _extract_case_file_evidence_ids(case_file_text)
    try:
        parsed, used_model = _call_with_fallback(
            token=token,
            endpoint=endpoint,
            model=model,
            fallback_model=fallback_model,
            messages=messages,
            fallback_label=engine_label,
            valid_evidence_ids=valid_evidence_ids,
            max_retries=max_retries,
            request_timeout=request_timeout,
        )
    except RuntimeError as err:
        return (
            {
                "status": "degraded",
                "label": None,
                "confidence": None,
                "judge_summary": "Court advisory degraded because the provider call failed.",
                "prosecutor_claims": [],
                "defender_claims": [],
                "accepted_arguments": [],
                "rejected_arguments": [],
                "unresolved_risks": [],
                "accepted_evidence_ids": [],
                "rejected_evidence_ids": [],
                "disagreement_reason": None,
            },
            str(err),
            None,
        )

    if parsed["label"] == engine_label:
        parsed["status"] = "aligned"
        parsed["disagreement_reason"] = None
        return parsed, None, used_model

    parsed["status"] = "manual_review"
    parsed["disagreement_reason"] = (
        f"Court verdict {parsed['label']} disagreed with deterministic decision {engine_label}."
    )
    return parsed, None, used_model
