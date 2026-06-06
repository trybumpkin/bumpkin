from __future__ import annotations

import json
import re
import urllib.request
from typing import Any, cast

COMMENT_MARKER = "<!-- bumpkin:recommendation -->"
BUMPKIN_TITLES = (
    "🤖 Bumpkin Recommendation",
    "🤖 Bumpkin (stub mode)",
    "🤖 Bumpkin (semantic fallback)",
    "🤖 Bumpkin Manual Review Required",
)
PATH_ONLY_EXPLAINABILITY_RULES = {"changed_file_path", "behavior_contract_path_signal"}
INTERNAL_TARGET_MEANING_MAP = {
    "snippet normalization": "text comparison hardening",
    "hint filtering": "explanation quality filtering",
    "dependency wiring": "integration wiring",
}
GENERIC_SEMANTIC_TARGET_LABELS = {
    "runtime/api behavior",
    "runtime api behavior",
    "internal runtime behavior",
    "runtime behavior",
    "internal behavior",
    "file content",
}
LOW_SIGNAL_IDENTIFIER_TOKENS = {
    "if",
    "for",
    "while",
    "return",
    "const",
    "let",
    "var",
    "def",
    "class",
    "function",
    "import",
    "from",
    "true",
    "false",
    "none",
    "null",
    "undefined",
    "runtime",
    "internal",
    "behavior",
    "content",
    "value",
    "text",
    "data",
    "item",
    "record",
}
LOW_SIGNAL_FINDINGS_SYMBOLS = LOW_SIGNAL_IDENTIFIER_TOKENS | {
    "location",
    "locations",
    "row",
    "rows",
    "line",
    "lines",
    "file",
    "files",
    "path",
    "paths",
    "rule",
    "rules",
    "scope",
    "scopes",
    "suggested",
    "summary",
    "details",
    "note",
    "notes",
}
AMBIGUOUS_TARGET_LABELS = {"compile", "format", "update", "parse"}


def _as_dict(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return cast("dict[str, Any]", value)


def _as_object_list(value: object) -> list[object] | None:
    if not isinstance(value, list):
        return None
    return cast("list[object]", value)


def format_recommendation_comment(
    result: dict[str, Any],
    notes: list[str],
    mode: str,
    fallback_reason: str | None = None,
    current_tag: str | None = None,
    next_tag: str | None = None,
    override_summary: str | None = None,
    findings: list[dict[str, Any]] | None = None,
    explainability_rows: list[dict[str, Any]] | None = None,
    aggregation_trace: str | None = None,
    boundary_summary: dict[str, int] | None = None,
    decision_trace: dict[str, Any] | None = None,
    analysis_state: str | None = None,
    classification_source: str | None = None,
    failure_category: str | None = None,
    policy_effects: list[str] | None = None,
    override_status: str | None = None,
    advisory_status: str | None = None,
    advisory_label: str | None = None,
    advisory_confidence: str | None = None,
    advisory_summary: str | None = None,
    disagreement_reason: str | None = None,
    advisory_fallback_reason: str | None = None,
    advisory_accepted_evidence_ids: list[str] | None = None,
    advisory_rejected_evidence_ids: list[str] | None = None,
    proof_obligations: dict[str, Any] | None = None,
    contradictions: list[dict[str, Any]] | None = None,
) -> str:
    status = str(result.get("status", "classified"))
    label = result.get("label")
    normalized_label = str(label).upper()
    emoji = {"PATCH": "🟢", "MINOR": "🟡", "MAJOR": "🔴", "NO_BUMP": "⚪"}.get(
        normalized_label, "⚪"
    )
    if status == "manual_review":
        title = "🤖 Bumpkin Manual Review Required"
    elif mode == "stub":
        title = "🤖 Bumpkin (stub mode)"
    elif mode == "fallback-heuristic":
        title = "🤖 Bumpkin (semantic fallback)"
    else:
        title = "🤖 Bumpkin Recommendation"
    findings_list = findings or []
    delta_rows = explainability_rows or []
    findings_block = _format_findings_block(
        findings_list,
        explainability_rows=delta_rows,
        status=status,
        classification_source=classification_source,
        advisory_status=advisory_status,
    )
    policy_block = _format_policy_effects_block(policy_effects or [])
    warning_block = ""
    if status == "manual_review":
        warning_block = "⚠️ Manual review required. Automatic model analysis could not produce a reliable result.\n"
        if fallback_reason:
            warning_block += f"Fallback reason: {fallback_reason}\n"
        warning_block += "\n"
    version_block = "Next version   : not computed\n"
    if status == "classified" and current_tag and next_tag:
        version_block = f"Next version   : {current_tag} → {next_tag}\n"
    elif status == "classified" and current_tag and not next_tag:
        version_block = f"Next version   : not computed (current={current_tag})\n"
    override_line = override_status or override_summary or "none"
    aggregation_block = ""
    if aggregation_trace:
        aggregation_block = f"Aggregation   : {aggregation_trace}\n"
    boundary_block = ""
    if boundary_summary:
        boundary_block = (
            "Boundary      : "
            f"public={int(boundary_summary.get('public', 0))}, "
            f"internal={int(boundary_summary.get('internal', 0))}, "
            f"unknown={int(boundary_summary.get('unknown', 0))}\n"
        )
    decision_block = _format_decision_trace_block(decision_trace or {})
    analysis_block = ""
    if analysis_state:
        source = classification_source or "unknown"
        analysis_block = f"Analysis state: {analysis_state} (source={source})\n"
        if failure_category:
            analysis_block += f"Failure class : {failure_category}\n"
    fallback_block = ""
    if fallback_reason and status != "manual_review":
        fallback_block = f"Fallback note : {_shorten(fallback_reason, limit=220)}\n"
    classified_summary = _format_classified_summary(
        explainability_rows=delta_rows,
    )
    reasoning_line = _format_reasoning_line(status=status, label=normalized_label)
    note_block = _format_notes_block(
        notes,
        status=status,
        label=label,
        confidence=result.get("confidence", "n/a"),
        classification_source=classification_source,
        advisory_status=advisory_status,
    )
    advisory_block = _format_advisory_block(
        status=advisory_status,
        label=advisory_label,
        confidence=advisory_confidence,
        summary=advisory_summary,
        disagreement_reason=disagreement_reason,
        fallback_reason=advisory_fallback_reason,
        accepted_evidence_ids=advisory_accepted_evidence_ids,
        rejected_evidence_ids=advisory_rejected_evidence_ids,
    )
    proposed_bump_line = _format_proposed_bump_line(
        advisory_label=advisory_label,
        advisory_confidence=advisory_confidence,
    )
    missing_proof_block = _format_missing_proof_obligations_block(proof_obligations or {})
    contradiction_block = _format_contradictions_block(contradictions or [])
    if status == "manual_review":
        details_block = _format_collapsed_details_block(
            analysis_block=analysis_block,
            fallback_block="",
            advisory_block=advisory_block,
            aggregation_block=aggregation_block,
            boundary_block=boundary_block,
            policy_block=policy_block,
            decision_block=decision_block,
            contradiction_block=contradiction_block,
            override_line=override_line,
            version_block="",
            note_block=note_block,
        )
        return (
            f"{COMMENT_MARKER}\n"
            f"{title}\n\n"
            f"{warning_block}"
            f"{proposed_bump_line}"
            "Final decision: manual review required.\n\n"
            f"{missing_proof_block}"
            f"Summary        : {classified_summary}\n\n"
            f"Reasoning      : {reasoning_line}\n\n"
            "Findings:\n"
            f"{findings_block}\n\n"
            f"{version_block}\n"
            f"{details_block}"
        )

    details_block = _format_collapsed_details_block(
        analysis_block=analysis_block,
        fallback_block=fallback_block,
        advisory_block=advisory_block,
        aggregation_block=aggregation_block,
        boundary_block=boundary_block,
        policy_block=policy_block,
        decision_block=decision_block,
        contradiction_block=contradiction_block,
        override_line=override_line,
        version_block="",
        note_block=note_block,
    )
    return (
        f"{COMMENT_MARKER}\n"
        f"{title}\n\n"
        f"Recommendation : {emoji} {label}\n"
        f"Confidence     : {result.get('confidence', 'n/a')}\n"
        f"Summary        : {classified_summary}\n\n"
        f"Reasoning      : {reasoning_line}\n\n"
        "Findings:\n"
        f"{findings_block}\n\n"
        f"{version_block}\n"
        f"{details_block}"
    )


def _format_classified_summary(
    *,
    explainability_rows: list[dict[str, Any]],
) -> str:
    semantic_rows = _semantic_delta_rows(explainability_rows)
    locations = _collect_semantic_locations(semantic_rows, max_items=2)
    public_count = sum(
        1
        for row in semantic_rows
        if str(row.get("impact_scope", "")).strip().lower() == "public_api"
    )
    internal_count = sum(
        1
        for row in semantic_rows
        if str(row.get("impact_scope", "")).strip().lower() == "runtime_internal"
    )
    return f"files affected: {locations}; public={public_count}, internal={internal_count}."


def _collect_semantic_locations(semantic_rows: list[dict[str, Any]], *, max_items: int) -> str:
    seen: set[str] = set()
    ordered: list[str] = []
    for row in semantic_rows:
        path = str(row.get("path", "")).strip()
        if not path:
            continue
        line_span = str(row.get("line_span", "")).strip()
        location = f"{path}:{line_span}" if line_span else path
        if location in seen:
            continue
        seen.add(location)
        ordered.append(location)
    if not ordered:
        return "none"
    listed = ordered[:max_items]
    remainder = len(ordered) - len(listed)
    if remainder > 0:
        listed.append(f"+{remainder} more")
    return ", ".join(listed)


def _format_reasoning_line(*, status: str, label: str) -> str:
    if str(status).strip().lower() == "manual_review":
        return "automatic classification unavailable; manual review required."
    normalized = str(label or "").strip().upper()
    if normalized == "MAJOR":
        return "public API breaking evidence detected."
    if normalized == "MINOR":
        return "public API additive evidence detected without breaking removal."
    if normalized == "PATCH":
        return "runtime-internal deltas detected; no public API evidence."
    if normalized == "NO_BUMP":
        return "non-runtime-only evidence detected; runtime/public impact not observed."
    return "semver decision derived from deterministic semantic evidence."


def _extract_identifier_from_snippet(snippet: str) -> str | None:
    if not snippet:
        return None
    patterns = (
        r"\b(?:def|class|function)\s+([A-Za-z_][A-Za-z0-9_]*)\b",
        r"\b(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\b",
        r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(",
    )
    for pattern in patterns:
        match = re.search(pattern, snippet)
        if not match:
            continue
        token = str(match.group(1)).strip()
        if token and token.lower() not in LOW_SIGNAL_IDENTIFIER_TOKENS:
            return token
    return None


def _format_findings_block(
    findings: list[dict[str, Any]],
    *,
    explainability_rows: list[dict[str, Any]],
    status: str,
    classification_source: str | None,
    advisory_status: str | None,
) -> str:
    semantic_rows = _semantic_delta_rows(explainability_rows)
    if semantic_rows:
        return _format_explainability_rows_block(semantic_rows)
    if findings:
        return _format_findings_fact_rows(findings)
    return "- none"


def _format_explainability_rows_block(explainability_rows: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    max_items = 4
    for row in explainability_rows[:max_items]:
        path = str(row.get("path", "unknown")).strip() or "unknown"
        line_span = str(row.get("line_span", "")).strip()
        location = f"{path}:{line_span}" if line_span else path
        rule = str(row.get("rule", "unknown_rule")).strip() or "unknown_rule"
        impact = str(row.get("impact_scope", "runtime_internal")).strip() or "runtime_internal"
        suggested = str(row.get("suggested_bump", "n/a")).strip() or "n/a"
        symbol = _extract_findings_symbol(row)
        line = f"- {location} | rule={rule} | scope={impact} | suggested={suggested}"
        if symbol:
            line += f" | symbol={symbol}"
        lines.append(line)
    remainder = len(explainability_rows) - max_items
    if remainder > 0:
        lines.append(f"- ... and {remainder} more delta row(s)")
    return "\n".join(lines)


def _format_findings_fact_rows(findings: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    max_items = 8
    for finding in findings[:max_items]:
        rule = str(finding.get("rule", "unknown_rule")).strip() or "unknown_rule"
        suggested = str(finding.get("suggested_bump") or "n/a").strip() or "n/a"
        scope = str(finding.get("impact_scope", "unknown")).strip() or "unknown"
        path = "unknown"
        line_span = str(finding.get("line_span", "")).strip()
        evidence = _as_object_list(finding.get("evidence", []))
        if evidence:
            first = _as_dict(evidence[0])
            if first is not None:
                path = str(first.get("path", "unknown")).strip() or "unknown"
                if not line_span:
                    line_span = str(first.get("line_span", "")).strip()
        location = f"{path}:{line_span}" if line_span else path
        symbol = _extract_findings_symbol(finding)
        line = f"- {location} | rule={rule} | scope={scope} | suggested={suggested}"
        if symbol:
            line += f" | symbol={symbol}"
        lines.append(line)
    remainder = len(findings) - max_items
    if remainder > 0:
        lines.append(f"- ... and {remainder} more finding(s)")
    return "\n".join(lines)


def _extract_findings_symbol(payload: dict[str, Any]) -> str | None:
    for key in ("symbol", "entity", "member", "function", "class_name", "name"):
        candidate = _normalize_symbol_candidate(payload.get(key))
        if candidate:
            return candidate
    target_candidate = _normalize_symbol_candidate(payload.get("target"))
    if target_candidate:
        return target_candidate
    for key in ("after", "before", "snippet"):
        candidate = _extract_identifier_from_snippet(str(payload.get(key, "")).strip())
        if candidate:
            return candidate
    evidence = _as_object_list(payload.get("evidence", []))
    if evidence:
        first = _as_dict(evidence[0])
        if first is not None:
            candidate = _extract_identifier_from_snippet(str(first.get("snippet", "")).strip())
            if candidate:
                return candidate
    return None


def _normalize_symbol_candidate(value: Any) -> str | None:
    token = str(value or "").strip().strip("`")
    if not token:
        return None
    lowered = token.lower()
    if lowered in GENERIC_SEMANTIC_TARGET_LABELS or lowered in AMBIGUOUS_TARGET_LABELS:
        return None
    if lowered in LOW_SIGNAL_FINDINGS_SYMBOLS:
        return None
    if any(ch.isspace() for ch in token):
        return None
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_\.]*$", token):
        return None
    return token


def _semantic_delta_rows(explainability_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    semantic_rows: list[dict[str, Any]] = []
    for row in explainability_rows:
        rule = str(row.get("rule", "")).strip().lower()
        if rule in PATH_ONLY_EXPLAINABILITY_RULES:
            continue
        semantic_rows.append(row)
    return semantic_rows


def _format_collapsed_details_block(
    *,
    analysis_block: str,
    fallback_block: str,
    advisory_block: str,
    aggregation_block: str,
    boundary_block: str,
    policy_block: str,
    decision_block: str,
    contradiction_block: str,
    override_line: str,
    version_block: str,
    note_block: str,
) -> str:
    sections: list[str] = []
    for block in (
        analysis_block,
        fallback_block,
        advisory_block,
        aggregation_block,
        boundary_block,
        decision_block,
        contradiction_block,
    ):
        normalized = block.strip()
        if normalized:
            sections.append(normalized)
    sections.append("Policy effects:\n" + policy_block.strip())
    sections.append(f"Override      : {override_line}")
    normalized_version = version_block.strip()
    if normalized_version:
        sections.append(normalized_version)
    sections.append("Notes:\n" + note_block.strip())
    details_body = "\n\n".join(sections).strip()
    return f"<details>\n<summary>Details</summary>\n\n{details_body}\n</details>\n"


def _format_contradictions_block(contradictions: list[dict[str, Any]]) -> str:
    if not contradictions:
        return ""
    lines = ["Contradictions:"]
    for item in contradictions[:4]:
        code = str(item.get("code", "")).strip() or "unknown"
        message = str(item.get("message", "")).strip() or "Contradiction detected."
        evidence_paths = _as_object_list(item.get("evidence_paths", []))
        evidence_suffix = ""
        if evidence_paths is not None:
            normalized = [str(path).strip() for path in evidence_paths if str(path).strip()]
            if normalized:
                evidence_suffix = f" [evidence={', '.join(normalized[:2])}]"
        lines.append(f"- {code}: {_shorten(message, limit=180)}{evidence_suffix}")
    remainder = len(contradictions) - 4
    if remainder > 0:
        lines.append(f"- ... and {remainder} more contradiction(s)")
    return "\n".join(lines)


def _format_proposed_bump_line(
    *,
    advisory_label: str | None,
    advisory_confidence: str | None,
) -> str:
    normalized_label = str(advisory_label or "").strip().upper()
    normalized_confidence = str(advisory_confidence or "").strip().lower() or "n/a"
    if not normalized_label:
        return "Proposed bump (court): n/a\n"
    return f"Proposed bump (court): {normalized_label} ({normalized_confidence} confidence)\n"


def _format_missing_proof_obligations_block(proof_obligations: dict[str, Any]) -> str:
    missing = _as_object_list(proof_obligations.get("missing", []))
    if not missing:
        return ""
    normalized = [str(item).strip() for item in missing if str(item).strip()]
    if not normalized:
        return ""
    lines = "Missing proof obligations:\n"
    for item in normalized[:5]:
        lines += f"- {item}\n"
    remainder = len(normalized) - 5
    if remainder > 0:
        lines += f"- ... and {remainder} more\n"
    return lines + "\n"


def _format_notes_block(
    notes: list[str],
    *,
    status: str,
    label: Any,
    confidence: Any,
    classification_source: str | None,
    advisory_status: str | None,
) -> str:
    if not notes:
        return "- none"

    unique_notes: list[str] = []
    seen: set[str] = set()
    for note in notes:
        normalized = str(note).strip()
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        if status == "classified" and _is_redundant_classified_note(
            normalized,
            label=label,
            confidence=confidence,
            classification_source=classification_source,
            advisory_status=advisory_status,
        ):
            continue
        unique_notes.append(normalized)

    if not unique_notes:
        return "- none"

    max_items = 6
    lines = [f"- {item}" for item in unique_notes[:max_items]]
    remainder = len(unique_notes) - max_items
    if remainder > 0:
        lines.append(f"- ... and {remainder} more note(s)")
    return "\n".join(lines)


def _is_redundant_classified_note(
    note: str,
    *,
    label: Any,
    confidence: Any,
    classification_source: str | None,
    advisory_status: str | None,
) -> bool:
    lowered = note.lower()
    if lowered.startswith("analysis state:"):
        return True

    summary_tokens = [
        f"label={str(label).lower()}",
        f"confidence={str(confidence).strip().lower()}",
        f"source={(classification_source or 'deterministic').lower()}",
        f"court={(advisory_status or 'n/a').lower()}",
    ]
    return any(token in lowered for token in summary_tokens)


def _format_policy_effects_block(policy_effects: list[str]) -> str:
    if not policy_effects:
        return "- none"
    filtered = [
        effect
        for effect in policy_effects
        if "configured; no effect" not in str(effect).strip().lower()
    ]
    if not filtered:
        return "- suppressed low-signal policy diagnostics"
    return "\n".join(f"- {effect}" for effect in filtered)


def _format_decision_trace_block(decision_trace: dict[str, Any]) -> str:
    if not decision_trace:
        return ""
    lines = ["Decision trace:"]
    base_label = decision_trace.get("base_label")
    final_label = decision_trace.get("final_label")
    if base_label or final_label:
        lines.append(f"- labels: base={base_label or 'n/a'} -> final={final_label or 'n/a'}")

    evidence_summary = _as_dict(decision_trace.get("evidence_summary"))
    if evidence_summary is not None:
        lines.append(
            "- evidence: "
            f"public={int(evidence_summary.get('strong_public_evidence', 0))}, "
            f"breaking={int(evidence_summary.get('strong_breaking_evidence', 0))}, "
            f"contract={int(evidence_summary.get('behavior_contract_evidence', 0))}"
        )

    noise_profile = _as_dict(decision_trace.get("noise_profile"))
    if noise_profile is not None:
        ratio = float(noise_profile.get("ratio", 0.0) or 0.0)
        changed = int(noise_profile.get("changed_files_total", 0) or 0)
        ignored = int(noise_profile.get("ignored_files_total", 0) or 0)
        lines.append(f"- noise: ratio={ratio:.2f} (ignored={ignored}/{changed})")

    contract_signals = _as_dict(decision_trace.get("behavior_contract_signals"))
    if contract_signals is not None:
        total = int(contract_signals.get("total", 0) or 0)
        if total > 0:
            samples = _as_object_list(contract_signals.get("sample_files"))
            sample_text = ""
            if samples:
                sample_text = f" [{', '.join(str(item) for item in samples[:2])}]"
            lines.append(f"- behavior contracts: {total} signal(s){sample_text}")

    actions = _as_object_list(decision_trace.get("policy_actions"))
    if not actions:
        return "\n".join(lines) + "\n\n"
    normalized_actions = [str(action).strip() for action in actions if str(action).strip()]
    if not normalized_actions:
        return "\n".join(lines) + "\n\n"
    lines.extend(f"- {action}" for action in normalized_actions[:6])
    remainder = len(normalized_actions) - 6
    if remainder > 0:
        lines.append(f"- ... and {remainder} more action(s)")
    return "\n".join(lines) + "\n\n"


def _format_advisory_block(
    *,
    status: str | None,
    label: str | None,
    confidence: str | None,
    summary: str | None,
    disagreement_reason: str | None,
    fallback_reason: str | None,
    accepted_evidence_ids: list[str] | None,
    rejected_evidence_ids: list[str] | None,
) -> str:
    normalized = (status or "skipped").strip().lower()
    label_text = str(label).upper() if label else "n/a"
    confidence_text = confidence or "n/a"
    out = [
        "Compatibility court:",
        f"- status={normalized}",
        f"- verdict={label_text}",
        f"- confidence={confidence_text}",
    ]
    if summary:
        out.append(f"- judge={_shorten(str(summary), limit=180)}")
    evidence_refs = _format_evidence_refs(
        accepted_evidence_ids=accepted_evidence_ids,
        rejected_evidence_ids=rejected_evidence_ids,
    )
    if evidence_refs:
        out.append(f"- evidence_refs={evidence_refs}")
    if fallback_reason:
        out.append(f"- degraded_reason={_shorten(str(fallback_reason), limit=180)}")
    if disagreement_reason:
        out.append(f"- disagreement={_shorten(str(disagreement_reason), limit=180)}")
    return "\n".join(out) + "\n\n"


def _format_evidence_refs(
    *,
    accepted_evidence_ids: list[str] | None,
    rejected_evidence_ids: list[str] | None,
) -> str:
    accepted = [str(item).strip() for item in (accepted_evidence_ids or []) if str(item).strip()]
    rejected = [str(item).strip() for item in (rejected_evidence_ids or []) if str(item).strip()]
    if not accepted and not rejected:
        return ""
    accepted_text = ", ".join(accepted[:4]) if accepted else "none"
    rejected_text = ", ".join(rejected[:3]) if rejected else "none"
    if len(accepted) > 4:
        accepted_text += f", +{len(accepted) - 4} more"
    if len(rejected) > 3:
        rejected_text += f", +{len(rejected) - 3} more"
    return f"accepted[{accepted_text}] rejected[{rejected_text}]"


def _shorten(value: str, *, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def _is_bumpkin_comment_body(body: str) -> bool:
    normalized = body.strip()
    return COMMENT_MARKER in normalized or normalized.startswith(BUMPKIN_TITLES)


def _find_existing_bumpkin_comment_id(comments: list[dict[str, Any]]) -> int | None:
    for comment in reversed(comments):
        body = str(comment.get("body", ""))
        if not _is_bumpkin_comment_body(body):
            continue
        comment_id = comment.get("id")
        if isinstance(comment_id, int):
            return comment_id
    return None


def _api_request(token: str, url: str, method: str, payload: dict[str, Any] | None = None) -> Any:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "bumpkin",
        },
    )
    with urllib.request.urlopen(req) as response:
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(
                f"GitHub API request failed: {method} {url} -> HTTP {response.status}"
            )
        content = response.read().decode("utf-8")
    return json.loads(content) if content else None


def post_pr_comment(token: str, repo: str, pr_number: int, body: str) -> None:
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required to post PR comments.")
    if not repo:
        raise RuntimeError("GITHUB_REPOSITORY is required to post PR comments.")

    comments_url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments?per_page=100"
    comments_raw = _api_request(token, comments_url, "GET")
    comments = _as_object_list(comments_raw)
    if comments is None:
        raise RuntimeError("Unexpected comments response shape from GitHub API.")
    typed_comments = [item for item in (_as_dict(entry) for entry in comments) if item is not None]

    existing_id = _find_existing_bumpkin_comment_id(typed_comments)
    if existing_id is not None:
        update_url = f"https://api.github.com/repos/{repo}/issues/comments/{existing_id}"
        _api_request(token, update_url, "PATCH", {"body": body})
        return

    create_url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    _api_request(token, create_url, "POST", {"body": body})
