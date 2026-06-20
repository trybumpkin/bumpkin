from __future__ import annotations

import json
import os
import re
import urllib.parse
from collections.abc import Callable
from typing import Any

from bumpkin.io.tokens import is_valid_models_endpoint, resolve_models_endpoint, resolve_models_token
from bumpkin.providers.llm_payloads import LLMResponseError, extract_content, extract_json_payload
from bumpkin.providers.llm_transport import LLMUnavailableError, post_json_request
from bumpkin.release.analysis import _normalize_label
from bumpkin.release.models import ReleaseRecommendationRecord

_PR_REFERENCE_RE = re.compile(r"\bPR\s+#(?P<number>\d+)\b")


def _top_label_records(
    recommendations: list[ReleaseRecommendationRecord],
    release_label: str | None,
) -> list[ReleaseRecommendationRecord]:
    normalized_label = _normalize_label(release_label)
    if normalized_label is None:
        return []
    return [
        record
        for record in recommendations
        if record.status == "classified" and record.label == normalized_label
    ]


def _parse_evidence_line(raw_line: str) -> dict[str, str]:
    parts = [part.strip() for part in raw_line.split("|") if part.strip()]
    if not parts:
        return {}
    parsed: dict[str, str] = {"path": parts[0]}
    for part in parts[1:]:
        key, sep, value = part.partition("=")
        if not sep:
            continue
        normalized_value = " ".join(value.split()).strip()
        if not normalized_value:
            continue
        parsed[key.strip().lower()] = normalized_value
    return parsed


def _format_preview_file_link(*, repository: str, target_sha: str, path: str) -> str:
    normalized_path = path.strip().lstrip("/")
    if not repository.strip() or not target_sha.strip() or not normalized_path:
        return path
    encoded_path = urllib.parse.quote(normalized_path, safe="/")
    return f"[`{normalized_path}`](https://github.com/{repository}/blob/{target_sha}/{encoded_path})"


def _format_rationale_sentence(
    *,
    record: ReleaseRecommendationRecord,
    evidence: dict[str, str],
    target_sha: str,
) -> str | None:
    path = evidence.get("path")
    rule = evidence.get("rule", "").lower()
    symbol = evidence.get("symbol", "").strip()
    scope = evidence.get("scope", "").lower()
    pr_number = record.pull_request.number

    if not path:
        return None
    linked_path = _format_preview_file_link(
        repository=record.pull_request.repository,
        target_sha=target_sha,
        path=path,
    )
    formatted_symbol = f"`{symbol}`" if symbol else ""

    if rule == "export_symbol_removed":
        if symbol:
            return f"PR #{pr_number} removed exported API {formatted_symbol} in {linked_path}."
        return f"PR #{pr_number} removed a public API surface in {linked_path}."
    if rule == "export_symbol_changed":
        if symbol:
            return f"PR #{pr_number} changed exported API {formatted_symbol} in {linked_path}."
        return f"PR #{pr_number} changed a public API surface in {linked_path}."
    if rule == "export_symbol_added":
        if symbol:
            return f"PR #{pr_number} added exported API {formatted_symbol} in {linked_path}."
        return f"PR #{pr_number} added a public API surface in {linked_path}."
    if scope == "public_api":
        return f"PR #{pr_number} changed public API behavior in {linked_path}."
    if scope == "runtime":
        return f"PR #{pr_number} changed runtime behavior in {linked_path}."
    return f"PR #{pr_number} changed code in {linked_path}."


def _fallback_rationale_sentence(record: ReleaseRecommendationRecord) -> str:
    summary = " ".join((record.summary or "").split()).strip()
    if summary:
        if summary.endswith("."):
            return f"PR #{record.pull_request.number}: {summary}"
        return f"PR #{record.pull_request.number}: {summary}."
    title = record.pull_request.title.rstrip(".")
    return f"PR #{record.pull_request.number} contributed to this release decision through {title}."


def _default_conclusion_line(release_label: str | None) -> str | None:
    normalized_label = _normalize_label(release_label)
    if normalized_label == "MAJOR":
        return "Breaking public APIs were removed or changed in this release batch."
    if normalized_label == "MINOR":
        return "No exported APIs were removed or narrowed in this release batch."
    if normalized_label == "PATCH":
        return "No public API additions or breaking removals were detected in this release batch."
    if normalized_label == "NO_BUMP":
        return "All included pull requests resolved to NO_BUMP."
    return None


def _build_release_why_lines(
    *,
    release_label: str | None,
    recommendations: list[ReleaseRecommendationRecord],
    target_sha: str,
) -> list[str]:
    normalized_label = _normalize_label(release_label)
    if normalized_label is None:
        return []
    matching_records = _top_label_records(recommendations, normalized_label)
    if not matching_records:
        return []
    lines: list[str] = []
    seen: set[str] = set()
    for record in matching_records:
        sentence: str | None = None
        for raw_line in record.evidence_lines:
            sentence = _format_rationale_sentence(
                record=record,
                evidence=_parse_evidence_line(raw_line),
                target_sha=target_sha,
            )
            if sentence:
                break
        if sentence is None:
            sentence = _fallback_rationale_sentence(record)
        if sentence in seen:
            continue
        seen.add(sentence)
        lines.append(sentence)
    conclusion = _default_conclusion_line(normalized_label)
    if conclusion:
        lines.append(conclusion)
    return lines


def _record_fact(record: ReleaseRecommendationRecord) -> dict[str, object]:
    evidence: list[dict[str, str]] = []
    for raw_line in record.evidence_lines[:3]:
        parsed = _parse_evidence_line(raw_line)
        if parsed:
            evidence.append(parsed)
    return {
        "number": record.pull_request.number,
        "title": record.pull_request.title,
        "label": record.label,
        "summary": record.summary or "",
        "reasoning": record.reasoning or "",
        "evidence": evidence,
    }


def _counts_by_label(recommendations: list[ReleaseRecommendationRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in recommendations:
        if record.status != "classified" or not record.label:
            continue
        counts[record.label] = counts.get(record.label, 0) + 1
    return counts


def _build_rationale_prompt_payload(
    *,
    release_label: str | None,
    recommendations: list[ReleaseRecommendationRecord],
) -> dict[str, object]:
    normalized_label = _normalize_label(release_label)
    winning_records = _top_label_records(recommendations, normalized_label)
    other_records = [
        record
        for record in recommendations
        if record.status == "classified" and record.label and record not in winning_records
    ]
    return {
        "release_label": normalized_label,
        "counts_by_label": _counts_by_label(recommendations),
        "winning_pull_requests": [_record_fact(record) for record in winning_records],
        "other_included_pull_requests": [
            {
                "number": record.pull_request.number,
                "title": record.pull_request.title,
                "label": record.label,
            }
            for record in other_records[:6]
        ],
        "conclusion_hint": _default_conclusion_line(normalized_label),
    }


def _build_rationale_messages(prompt_payload: dict[str, object]) -> list[dict[str, str]]:
    instructions = (
        "You rewrite maintainer-facing release rationale bullets from deterministic release facts. "
        "Return JSON only with the shape {\"lines\":[\"...\"]}. "
        "Use 2 to 5 short bullets. "
        "Use plain English, mention PR numbers when relevant, and explain what changed in user-facing terms. "
        "Use only the provided facts. Do not invent files, symbols, or PR numbers. "
        "The final bullet should summarize why the overall release label was chosen. "
        "If lower-severity PRs are also included, you may mention them briefly in that summary bullet."
    )
    return [
        {"role": "system", "content": instructions},
        {"role": "user", "content": json.dumps(prompt_payload, indent=2, sort_keys=True)},
    ]


def _coerce_rationale_lines(payload: dict[str, Any]) -> list[str]:
    raw_lines = payload.get("lines")
    if isinstance(raw_lines, str):
        candidate_lines = [line.strip() for line in raw_lines.splitlines() if line.strip()]
    elif isinstance(raw_lines, list):
        candidate_lines = [str(item).strip() for item in raw_lines if str(item).strip()]
    else:
        raise LLMResponseError("Model rationale output did not include a lines array.")
    cleaned_lines = [line.removeprefix("- ").strip() for line in candidate_lines if line.strip()]
    if not 2 <= len(cleaned_lines) <= 5:
        raise LLMResponseError("Model rationale output must contain between 2 and 5 lines.")
    return cleaned_lines


def _validate_rationale_lines(lines: list[str], *, allowed_pr_numbers: set[int]) -> list[str]:
    for line in lines:
        for match in _PR_REFERENCE_RE.finditer(line):
            pr_number = int(match.group("number"))
            if pr_number not in allowed_pr_numbers:
                raise LLMResponseError("Model rationale referenced a pull request outside the release scope.")
    return lines


def _request_rationale_rewrite(
    *,
    prompt_payload: dict[str, object],
    model: str,
    token: str,
    endpoint: str,
    max_retries: int,
    request_timeout: int,
    post_json_request_fn: Callable[..., dict[str, Any]],
) -> list[str]:
    raw = post_json_request_fn(
        endpoint=endpoint,
        token=token,
        payload={
            "model": model,
            "messages": _build_rationale_messages(prompt_payload),
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_tokens": 350,
        },
        max_retries=max_retries,
        request_timeout=request_timeout,
    )
    content = extract_content(raw)
    payload = extract_json_payload(content)
    return _coerce_rationale_lines(payload)


def resolve_preview_rationale_lines(
    *,
    release_label: str | None,
    recommendations: list[ReleaseRecommendationRecord],
    target_sha: str,
    model: str | None = None,
    fallback_model: str | None = None,
    models_endpoint: str | None = None,
    models_token: str | None = None,
    max_retries: int = 3,
    request_timeout: int = 45,
    post_json_request_fn: Callable[..., dict[str, Any]] = post_json_request,
) -> list[str]:
    fallback_lines = _build_release_why_lines(
        release_label=release_label,
        recommendations=recommendations,
        target_sha=target_sha,
    )
    normalized_label = _normalize_label(release_label)
    if normalized_label is None or not fallback_lines:
        return fallback_lines

    prompt_payload = _build_rationale_prompt_payload(
        release_label=normalized_label,
        recommendations=recommendations,
    )
    if not prompt_payload["winning_pull_requests"]:
        return fallback_lines

    endpoint = (models_endpoint or resolve_models_endpoint()).strip()
    primary_model = (model or os.getenv("BUMPKIN_MODEL", "")).strip()
    secondary_model = (fallback_model or os.getenv("BUMPKIN_FALLBACK_MODEL", "")).strip()
    token = (models_token or resolve_models_token(endpoint=endpoint)).strip()
    if not endpoint or not primary_model or not token or not is_valid_models_endpoint(endpoint):
        return fallback_lines

    allowed_pr_numbers = {
        record.pull_request.number
        for record in recommendations
        if record.status == "classified" and record.label
    }

    candidate_models = [primary_model]
    if secondary_model and secondary_model != primary_model:
        candidate_models.append(secondary_model)

    for candidate_model in candidate_models:
        try:
            lines = _request_rationale_rewrite(
                prompt_payload=prompt_payload,
                model=candidate_model,
                token=token,
                endpoint=endpoint,
                max_retries=max_retries,
                request_timeout=request_timeout,
                post_json_request_fn=post_json_request_fn,
            )
            return _validate_rationale_lines(lines, allowed_pr_numbers=allowed_pr_numbers)
        except (LLMUnavailableError, LLMResponseError):
            continue

    return fallback_lines


__all__ = [
    "_build_release_why_lines",
    "resolve_preview_rationale_lines",
]
