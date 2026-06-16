from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Any, cast

from bumpkin.orchestrator import court as orchestrator_court
from bumpkin.retry import (
    apply_model_call_interval,
    compute_retry_delay,
    is_retryable_http_code,
    register_rate_limit_cooldown,
)

MACHINE_EXPLANATION_PATTERN = re.compile(
    r"\b(?:path_marker|behavior_marker|contract_signal):\d+\b|"
    r"\b(?:changed_file_path|behavior_contract_path_signal|added_external_side_effect|added_throw_statement)\b"
)
CHANGELOG_PATTERN = re.compile(
    r"^(feat|fix|chore|refactor|perf|docs|build|ci|test|style)(\([^)]+\))?(!)?:\s+\S"
)
POLISH_SCHEMA_NAME = "explanation_polish_v1"
POLISH_MAX_OUTPUT_TOKENS = 120
POLISH_REPAIR_MAX_OUTPUT_TOKENS = 96
POLISH_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "reasoning": {"type": "string", "minLength": 32},
        "changelog": {"type": "string", "minLength": 12},
    },
    "required": ["reasoning", "changelog"],
}


def _as_dict(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return cast("dict[str, Any]", value)


def is_human_readable_explanation(text: str) -> bool:
    normalized = " ".join(str(text or "").split()).strip().lower()
    if not normalized:
        return False
    return MACHINE_EXPLANATION_PATTERN.search(normalized) is None


def should_run_explanation_polish(
    *, reasoning: str, changelog: str, confidence: str, token: str
) -> bool:
    if not token:
        return False
    normalized_reasoning = " ".join(reasoning.split()).strip().lower()
    normalized_changelog = " ".join(changelog.split()).strip().lower()
    score = 0
    if is_human_readable_explanation(reasoning) and is_human_readable_explanation(changelog):
        score += 1
    if len(normalized_reasoning) >= 96:
        score += 1
    if "more file(s)" not in normalized_reasoning and "more file(s)" not in normalized_changelog:
        score += 1
    if any(
        marker in (normalized_reasoning + " " + normalized_changelog)
        for marker in (".py", ".ts", ".js", ".go", ".rs", ".java", ".kt")
    ):
        score += 1
    if "accepted evidence indicates" not in normalized_reasoning:
        score += 1
    normalized_confidence = confidence.strip().lower()
    if (
        normalized_confidence == "low"
        and normalized_reasoning.startswith("court selected ")
        and "accepted evidence indicates" in normalized_reasoning
    ):
        return True
    threshold = 4 if normalized_confidence == "low" else 3
    return score < threshold


def _filename_from_path(path: str) -> str:
    normalized = str(path or "").strip().replace("\\", "/")
    if not normalized:
        return ""
    return normalized.rsplit("/", 1)[-1].strip().lower()


def _humanize_rule(rule: str) -> str:
    normalized = str(rule or "").strip().lower()
    mapping = {
        "changed_file_path": "file changed",
        "added_external_side_effect": "external side effect added",
        "added_throw_statement": "error path added",
        "removed_guard_branch": "guard branch removed",
        "behavior_contract_path_signal": "contract path touched",
    }
    if normalized in mapping:
        return mapping[normalized]
    if not normalized:
        return "internal behavior updated"
    return normalized.replace("_", " ")


def _build_polish_messages(
    *,
    advisory_label: str,
    draft_reasoning: str,
    draft_changelog: str,
    records: list[dict[str, str]],
) -> list[dict[str, str]]:
    facts: list[dict[str, str]] = []
    for record in records[:3]:
        path = str(record.get("path", "")).strip()
        facts.append(
            {
                "path": path,
                "file": path.rsplit("/", 1)[-1] if path else "<unknown>",
                "signal": _humanize_rule(str(record.get("rule", ""))),
            }
        )

    system = (
        "Rewrite reasoning and changelog for readability. Keep facts faithful to provided evidence. "
        "Do not invent files or impacts. Do not include internal IDs or snake_case rule names. "
        'Return strict JSON: {"reasoning": string, "changelog": string}. '
        "Use conventional commit format for changelog."
    )
    user = json.dumps(
        {
            "label": advisory_label,
            "draft_reasoning": draft_reasoning,
            "draft_changelog": draft_changelog,
            "evidence_facts": facts,
            "requirements": {
                "reasoning_max_chars": 220,
                "must_mention_at_least_one_file": True,
                "must_preserve_label_intent": True,
            },
        },
        ensure_ascii=True,
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _build_polish_repair_messages(
    *,
    raw_output: str,
    file_anchors: set[str],
) -> list[dict[str, str]]:
    anchors = sorted(anchor for anchor in file_anchors if anchor)[:3]
    system = (
        "You repair malformed explanation polish output into strict JSON. "
        'Return one object only: {"reasoning": string, "changelog": string}. '
        "Use conventional commit format for changelog. "
        "Keep wording concise and human-readable."
    )
    user = json.dumps(
        {
            "required_file_anchors": anchors,
            "malformed_output": raw_output[:1400],
            "constraints": {
                "reasoning_max_chars": 220,
                "no_internal_ids": True,
                "must_include_one_anchor_when_available": bool(anchors),
            },
        },
        ensure_ascii=True,
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _recover_polish_payload_from_text(content: str) -> dict[str, Any] | None:
    text = content.strip()
    if not text:
        return None
    reasoning_match = re.search(
        r"(?:^|\n)\s*reasoning\s*[:\-]\s*(.+?)(?:\n|$)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    changelog_match = re.search(
        r"(?:^|\n)\s*changelog\s*[:\-]\s*([^\n]+)",
        text,
        flags=re.IGNORECASE,
    )
    if reasoning_match and changelog_match:
        return {
            "reasoning": " ".join(reasoning_match.group(1).split()).strip(),
            "changelog": " ".join(changelog_match.group(1).split()).strip(),
        }
    extracted_changelog = ""
    if changelog_match:
        extracted_changelog = " ".join(changelog_match.group(1).split()).strip()
    if not extracted_changelog:
        for raw_line in text.splitlines():
            line = raw_line.strip().lstrip("-* ").strip()
            if not line:
                continue
            match = CHANGELOG_PATTERN.search(line)
            if match:
                extracted_changelog = line[match.start() :].strip().strip("`")
                break
            inline_match = re.search(
                r"(feat|fix|chore|refactor|perf|docs|build|ci|test|style)(\([^)]+\))?(!)?:\s+\S.+$",
                line,
                flags=re.IGNORECASE,
            )
            if inline_match:
                extracted_changelog = line[inline_match.start() :].strip().strip("`")
                break
    if not extracted_changelog:
        overall_match = CHANGELOG_PATTERN.search(text)
        if overall_match:
            tail = text[overall_match.start() :].splitlines()[0].strip()
            extracted_changelog = tail.strip("`")

    extracted_reasoning = ""
    if reasoning_match:
        extracted_reasoning = " ".join(reasoning_match.group(1).split()).strip()
    elif extracted_changelog:
        reasoning_source = text.replace(extracted_changelog, " ")
        extracted_reasoning = " ".join(reasoning_source.split()).strip()
        if extracted_reasoning.lower().startswith("changelog:"):
            extracted_reasoning = extracted_reasoning.split(":", 1)[1].strip()

    if extracted_reasoning and extracted_changelog:
        return {
            "reasoning": extracted_reasoning,
            "changelog": extracted_changelog,
        }
    return None


def extract_polish_payload(content: str) -> dict[str, Any]:
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
    except ValueError:
        pass

    for candidate in orchestrator_court.iter_json_object_slices(text):
        try:
            parsed = json.loads(candidate)
            parsed_dict = _as_dict(parsed)
            if parsed_dict is not None:
                return parsed_dict
            if isinstance(parsed, str):
                nested = json.loads(parsed)
                nested_dict = _as_dict(nested)
                if nested_dict is not None:
                    return nested_dict
        except ValueError:
            continue
    recovered = _recover_polish_payload_from_text(text)
    if recovered is not None:
        return recovered
    raise RuntimeError("Polish model returned non-JSON output.")


def validate_polish_payload(payload: dict[str, Any], *, file_anchors: set[str]) -> tuple[str, str]:
    reasoning = " ".join(str(payload.get("reasoning", "")).split()).strip()
    changelog = " ".join(str(payload.get("changelog", "")).split()).strip()
    if len(reasoning) < 32:
        raise RuntimeError("Polish reasoning is too short.")
    if len(changelog) < 12:
        raise RuntimeError("Polish changelog is too short.")
    if len(reasoning) > 240:
        reasoning = reasoning[:237].rstrip() + "..."
    if len(changelog) > 120:
        changelog = changelog[:117].rstrip() + "..."
    if not CHANGELOG_PATTERN.match(changelog):
        raise RuntimeError("Polish changelog is not in conventional commit format.")
    if not is_human_readable_explanation(reasoning):
        raise RuntimeError("Polish reasoning leaked machine tokens.")
    if not is_human_readable_explanation(changelog):
        raise RuntimeError("Polish changelog leaked machine tokens.")
    if file_anchors:
        joined = f"{reasoning.lower()} {changelog.lower()}"
        if not any(anchor in joined for anchor in file_anchors):
            raise RuntimeError("Polish output omitted required file anchors.")
    return reasoning, changelog


def _attempt_polish_repair(
    *,
    token: str,
    endpoint: str,
    model: str,
    raw_output: str,
    file_anchors: set[str],
    request_timeout: int,
) -> tuple[str, str]:
    payload = {
        "model": model,
        "messages": _build_polish_repair_messages(
            raw_output=raw_output,
            file_anchors=file_anchors,
        ),
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": POLISH_SCHEMA_NAME,
                "strict": True,
                "schema": POLISH_RESPONSE_SCHEMA,
            },
        },
        "temperature": 0,
        "max_tokens": POLISH_REPAIR_MAX_OUTPUT_TOKENS,
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers=orchestrator_court.request_headers(token, endpoint),
    )
    try:
        with urllib.request.urlopen(req, timeout=max(1, request_timeout)) as response:
            raw = json.loads(response.read().decode("utf-8"))
        content = orchestrator_court.extract_content(raw)
        parsed = extract_polish_payload(content)
        return validate_polish_payload(parsed, file_anchors=file_anchors)
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"repair_http_{err.code}: {body[:180]}") from err
    except urllib.error.URLError as err:
        raise RuntimeError(f"repair_url_error: {err.reason}") from err
    except TimeoutError as err:
        raise RuntimeError(str(err) or "repair request timed out") from err
    except (ValueError, RuntimeError) as err:
        raise RuntimeError(f"repair_parse_error: {err}") from err


def polish_explanation_with_model(
    *,
    advisory_label: str,
    draft_reasoning: str,
    draft_changelog: str,
    records: list[dict[str, str]],
    token: str,
    endpoint: str,
    model: str,
    max_retries: int,
    request_timeout: int,
) -> tuple[str, str, bool, str | None]:
    if not token:
        return draft_reasoning, draft_changelog, False, "missing_model_token"
    if not records:
        return draft_reasoning, draft_changelog, False, "missing_evidence_records"
    file_anchors = {
        _filename_from_path(str(item.get("path", "")))
        for item in records
        if _filename_from_path(str(item.get("path", "")))
    }
    payload = {
        "model": model,
        "messages": _build_polish_messages(
            advisory_label=advisory_label,
            draft_reasoning=draft_reasoning,
            draft_changelog=draft_changelog,
            records=records,
        ),
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": POLISH_SCHEMA_NAME,
                "strict": True,
                "schema": POLISH_RESPONSE_SCHEMA,
            },
        },
        "temperature": 0,
        "max_tokens": POLISH_MAX_OUTPUT_TOKENS,
    }

    attempts = max(1, min(max_retries, 2))
    last_error = "unknown"
    for attempt in range(attempts):
        apply_model_call_interval()
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers=orchestrator_court.request_headers(token, endpoint),
        )
        try:
            with urllib.request.urlopen(req, timeout=max(1, request_timeout)) as response:
                raw = json.loads(response.read().decode("utf-8"))
            content = orchestrator_court.extract_content(raw)
            try:
                parsed = extract_polish_payload(content)
                reasoning, changelog = validate_polish_payload(parsed, file_anchors=file_anchors)
                return reasoning, changelog, True, None
            except RuntimeError as parse_err:
                try:
                    reasoning, changelog = _attempt_polish_repair(
                        token=token,
                        endpoint=endpoint,
                        model=model,
                        raw_output=content,
                        file_anchors=file_anchors,
                        request_timeout=request_timeout,
                    )
                    return reasoning, changelog, True, None
                except RuntimeError as repair_err:
                    last_error = f"{parse_err}; repair_failed={repair_err}"
                    if attempt < attempts - 1:
                        time.sleep(compute_retry_delay(attempt_index=attempt))
                        continue
                    break
        except urllib.error.HTTPError as err:
            body = err.read().decode("utf-8", errors="replace")
            last_error = f"HTTP {err.code}: {body[:220]}"
            if is_retryable_http_code(err.code) and attempt < attempts - 1:
                if err.code == 429:
                    register_rate_limit_cooldown(headers=err.headers, minimum_seconds=60.0)
                delay = compute_retry_delay(attempt_index=attempt, headers=err.headers)
                time.sleep(delay)
                continue
            break
        except urllib.error.URLError as err:
            last_error = f"url_error: {err.reason}"
            if attempt < attempts - 1:
                time.sleep(compute_retry_delay(attempt_index=attempt))
                continue
            break
        except TimeoutError as err:
            last_error = str(err) or "request timed out"
            if attempt < attempts - 1:
                time.sleep(compute_retry_delay(attempt_index=attempt))
                continue
            break
        except (ValueError, RuntimeError) as err:
            last_error = str(err)
            if attempt < attempts - 1:
                time.sleep(compute_retry_delay(attempt_index=attempt))
                continue
            break
    return draft_reasoning, draft_changelog, False, last_error
