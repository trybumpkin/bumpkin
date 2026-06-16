from __future__ import annotations

import re
from dataclasses import dataclass

LOW_SIGNAL_HINT_SYMBOLS = {
    "normalized_snippet",
    "normalized_text",
    "snippet",
    "compact",
    "value",
    "text",
    "data",
    "item",
    "record",
    "path",
    "symbol_name",
}

MARKER_TOKEN_PATTERN = re.compile(
    r"\b(?:path_marker|behavior_marker|contract_signal):\d+\b|"
    r"\b(?:changed_file_path|behavior_contract_path_signal)\b"
)
CONSTANT_LEAK_PATTERN = re.compile(r"\b[A-Z]{3,}_[A-Z0-9_]{3,}\b")
RAW_REGEX_PATTERN = re.compile(r"(^r[\"'])|\\[bdswDSW]|\[[^\]]+\]\*?")
IMPORT_ONLY_PATTERN = re.compile(
    r"^\s*(?:import\s+.+|from\s+\S+\s+import\s+.+|(?:const|let|var)\s+\w+\s*=\s*require\(.+\))\s*;?\s*$"
)

HINT_CATEGORY_PRIORITY = {
    "behavior_change": 500,
    "api_symbol": 450,
    "control_flow": 400,
    "generic": 300,
    "regex_pattern": 200,
    "import_only": 100,
}

INTERNAL_HINT_MEANING_MAP = {
    "snippet normalization": "text comparison hardening",
    "hint filtering": "explanation quality filtering",
    "dependency wiring": "integration wiring",
}

PATH_ONLY_DELTA_RULES = {"changed_file_path", "behavior_contract_path_signal"}


@dataclass(frozen=True)
class ExplanationFacts:
    label: str
    target_summary: str
    scope: str
    operation_hint: str | None
    has_path_targets: bool


@dataclass(frozen=True)
class HintCandidate:
    hint: str
    category: str
    priority: int
    order: int


@dataclass(frozen=True)
class DeltaRow:
    path: str
    line_span: str | None
    rule: str
    action: str
    target: str
    impact_scope: str
    suggested_bump: str
    severity: str
    before: str | None = None
    after: str | None = None
    impact_reason: str | None = None

    def to_dict(self) -> dict[str, str]:
        payload = {
            "path": self.path,
            "rule": self.rule,
            "action": self.action,
            "target": self.target,
            "impact_scope": self.impact_scope,
            "suggested_bump": self.suggested_bump,
            "severity": self.severity,
        }
        if self.line_span:
            payload["line_span"] = self.line_span
        if self.before:
            payload["before"] = self.before
        if self.after:
            payload["after"] = self.after
        if self.impact_reason:
            payload["impact_reason"] = self.impact_reason
        return payload


def supports_label(label: str) -> bool:
    return label.upper() in {"MAJOR", "MINOR", "PATCH", "NO_BUMP"}


def is_path_only_delta_rule(rule: str) -> bool:
    return str(rule).strip().lower() in PATH_ONLY_DELTA_RULES


def is_semantic_delta_row(row: dict[str, str]) -> bool:
    return not is_path_only_delta_rule(str(row.get("rule", "")))


def filter_semantic_delta_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in rows if is_semantic_delta_row(row)]


def derive_scope_from_path(path: str, *, rule: str) -> str:
    normalized = str(path or "").strip().replace("\\", "/").lstrip("/")
    if normalized:
        parts = [part for part in normalized.split("/") if part]
        generic_scopes = {"bumpkin", "services", "service", "internal", "lib", "app"}
        if len(parts) >= 3 and parts[0] == "src" and parts[1] in generic_scopes:
            scope = parts[2]
        elif len(parts) >= 2 and parts[0] == "src":
            scope = parts[1]
        elif len(parts) >= 2:
            scope = parts[-2]
        else:
            scope = parts[0].split(".", 1)[0]
    else:
        scope = str(rule or "").strip().replace("_", "-")
    compact = "".join(ch for ch in scope.lower() if ch.isalnum() or ch in {"-", "_"})
    return compact or "core"


def summarize_path_targets(paths: list[str], *, max_items: int = 2) -> str:
    normalized = [path.strip() for path in paths if path.strip()]
    if not normalized:
        return "updated files"
    seen_filenames: set[str] = set()
    filenames: list[str] = []
    for path in normalized:
        filename = path.rsplit("/", 1)[-1]
        if filename in seen_filenames:
            continue
        seen_filenames.add(filename)
        filenames.append(filename)
    shown = filenames[:max_items]
    if len(filenames) == 1:
        return shown[0]
    if len(filenames) == 2:
        return f"{shown[0]} and {shown[1]}"
    return f"{', '.join(shown)} and {len(filenames) - max_items} more file(s)"


def extract_symbol_hint(snippet: str) -> str | None:
    patterns: list[tuple[str, str]] = [
        (r"\bdef\s+([A-Za-z_][A-Za-z0-9_]*)\b", "function"),
        (r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)\b", "class"),
        (r"\bexport\s+(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)\b", "function"),
        (r"\bfunction\s+([A-Za-z_$][A-Za-z0-9_$]*)\b", "function"),
        (r"\b(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=", "assignment"),
        (r"\b([A-Za-z_][A-Za-z0-9_]*)\s*:\s*[^=]+\s*=", "assignment"),
        (r"\b([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)", "assignment"),
    ]
    for pattern, kind in patterns:
        match = re.search(pattern, snippet)
        if not match:
            continue
        symbol = match.group(1).strip()
        if not symbol:
            continue
        lowered = symbol.lower()
        if kind == "assignment" and (lowered in LOW_SIGNAL_HINT_SYMBOLS or symbol.isupper()):
            return None
        return f"`{symbol}`"
    return None


def derive_operation_hint(snippet: str) -> str | None:
    lowered = snippet.lower()
    if ".lower()" in snippet or "normalize" in lowered:
        return "`snippet normalization`"
    if "startswith(" in lowered or "endswith(" in lowered:
        return "`pattern check`"
    if " in " in lowered and "low_signal_hint_symbols" in lowered:
        return "`hint filtering`"
    if "if " in lowered or "elif " in lowered or "else:" in lowered:
        return "`control-flow handling`"
    return None


def _sanitize_compact_snippet(snippet: str) -> str | None:
    compact = re.sub(r"\s+", " ", snippet).strip("`'\" ")
    if len(compact) < 8:
        return None
    if MARKER_TOKEN_PATTERN.search(compact):
        return None
    if CONSTANT_LEAK_PATTERN.search(compact):
        return None
    if RAW_REGEX_PATTERN.search(compact):
        return None
    if len(compact) > 64:
        compact = compact[:61].rstrip() + "..."
    return f"`{compact}`"


def _classify_snippet(snippet: str) -> str:
    lowered = snippet.lower()
    if IMPORT_ONLY_PATTERN.match(snippet):
        return "import_only"
    if any(
        token in lowered
        for token in ("throw ", "raise ", "process.exit(", "fetch(", "axios.", "request(")
    ):
        return "behavior_change"
    if any(token in lowered for token in ("if ", "elif ", "else:", "match ", "case ")):
        return "control_flow"
    if (
        snippet.startswith(('r"', "r'"))
        or "\\b" in snippet
        or "\\s*" in snippet
        or "\\d" in snippet
    ):
        return "regex_pattern"
    return "generic"


def _best_hint(candidates: list[HintCandidate]) -> str | None:
    if not candidates:
        return None
    ranked = sorted(candidates, key=lambda item: (-item.priority, item.order))
    return ranked[0].hint


def _apply_internal_hint_meaning_map(hint: str | None) -> str | None:
    normalized = str(hint or "").strip()
    if not normalized:
        return None
    token = normalized.strip("`").strip().lower()
    mapped = INTERNAL_HINT_MEANING_MAP.get(token)
    if not mapped:
        return normalized
    return f"`{mapped}`"


def change_hint_from_records(records: list[dict[str, str]]) -> str | None:
    candidates: list[HintCandidate] = []
    for record in records:
        order = len(candidates)
        path = str(record.get("path", "")).strip().lower()
        snippet = " ".join(str(record.get("snippet", "")).split()).strip()
        if not snippet:
            continue
        if path and snippet.lower() in {path, path.rsplit("/", 1)[-1]}:
            continue
        category = _classify_snippet(snippet)

        if category == "import_only":
            candidates.append(
                HintCandidate(
                    hint="`dependency wiring`",
                    category="import_only",
                    priority=HINT_CATEGORY_PRIORITY["import_only"],
                    order=order,
                )
            )
            continue

        symbol_hint = extract_symbol_hint(snippet)
        if symbol_hint:
            candidates.append(
                HintCandidate(
                    hint=symbol_hint,
                    category="api_symbol",
                    priority=HINT_CATEGORY_PRIORITY["api_symbol"],
                    order=order,
                )
            )
            continue

        operation_hint = derive_operation_hint(snippet)
        if operation_hint:
            derived_category = (
                "behavior_change" if category == "behavior_change" else "control_flow"
            )
            candidates.append(
                HintCandidate(
                    hint=operation_hint,
                    category=derived_category,
                    priority=HINT_CATEGORY_PRIORITY[derived_category],
                    order=order,
                )
            )
            continue

        if (
            snippet.startswith(('r"', "r'"))
            or "\\b" in snippet
            or "\\s*" in snippet
            or "\\d" in snippet
            or RAW_REGEX_PATTERN.search(snippet)
        ):
            candidates.append(
                HintCandidate(
                    hint="`regex pattern`",
                    category="regex_pattern",
                    priority=HINT_CATEGORY_PRIORITY["regex_pattern"],
                    order=order,
                )
            )
            continue
        compact = _sanitize_compact_snippet(snippet)
        if compact:
            candidates.append(
                HintCandidate(
                    hint=compact,
                    category="generic",
                    priority=HINT_CATEGORY_PRIORITY["generic"],
                    order=order,
                )
            )
    return _apply_internal_hint_meaning_map(_best_hint(candidates))


def build_explanation_facts(
    *,
    advisory_label: str,
    records: list[dict[str, str]],
    max_target_items: int = 2,
) -> ExplanationFacts | None:
    label = advisory_label.upper()
    if not supports_label(label):
        return None
    paths = [
        str(record.get("path", "")).strip()
        for record in records
        if str(record.get("path", "")).strip()
    ]
    target_summary = summarize_path_targets(paths, max_items=max_target_items)
    primary = records[0] if records else {"path": "", "rule": ""}
    scope = derive_scope_from_path(
        paths[0] if paths else str(primary.get("path", "")),
        rule=str(primary.get("rule", "")),
    )
    return ExplanationFacts(
        label=label,
        target_summary=target_summary,
        scope=scope,
        operation_hint=change_hint_from_records(records),
        has_path_targets=bool(paths),
    )


def _severity_rank(label: str) -> int:
    ordering = {"MAJOR": 4, "MINOR": 3, "PATCH": 2, "NO_BUMP": 1}
    return ordering.get(label.upper(), 0)


def _action_priority(action: str) -> int:
    ordering = {"removed": 5, "renamed": 4, "tightened": 3, "added": 2, "changed": 1, "modified": 0}
    return ordering.get(action, 0)


def _derive_delta_action(*, rule: str, snippet: str) -> str:
    lowered_rule = rule.lower()
    lowered_snippet = snippet.lower()
    if "runtime_contract_unchanged" in lowered_rule:
        return "unchanged"
    if lowered_rule == "changed_file_path":
        return "modified"
    if (
        any(token in lowered_rule for token in ("removed", "delete", "breaking"))
        or " remove" in lowered_snippet
    ):
        return "removed"
    if "rename" in lowered_rule or " rename" in lowered_snippet:
        return "renamed"
    if any(token in lowered_rule for token in ("required", "signature", "tightening")):
        return "tightened"
    if (
        any(token in lowered_rule for token in ("added", "introduce", "new_"))
        or " add" in lowered_snippet
    ):
        return "added"
    if "change" in lowered_rule or "changed" in lowered_snippet:
        return "changed"
    return "modified"


def _derive_delta_target(*, rule: str, snippet: str) -> str:
    symbol_hint = extract_symbol_hint(snippet)
    if symbol_hint:
        return symbol_hint.strip("`")
    operation_hint = derive_operation_hint(snippet)
    if operation_hint:
        return operation_hint.strip("`")
    lowered_rule = rule.lower()
    if "export_symbol" in lowered_rule:
        return "exported symbol(s)"
    if "signature" in lowered_rule or "requiredness" in lowered_rule:
        return "exported API signature"
    if "runtime_contract_unchanged" in lowered_rule:
        return "runtime contract"
    if "internal_runtime_delta" in lowered_rule:
        return "internal runtime behavior"
    if "changed_file_path" in lowered_rule:
        return "file content"
    normalized_rule = lowered_rule.replace("_", " ").strip()
    return normalized_rule or "runtime/API behavior"


def _derive_impact_scope(*, path: str, rule: str) -> str:
    lowered_path = path.lower()
    lowered_rule = rule.lower()
    if (
        "export_" in lowered_rule
        or "public" in lowered_rule
        or "contract" in lowered_rule
        or lowered_path.startswith("src/api/")
    ):
        return "public_api"
    if "runtime_contract_unchanged" in lowered_rule:
        return "non_runtime"
    if lowered_path.startswith((".github/", "docs/")) or lowered_path.endswith(".md"):
        return "non_runtime"
    return "runtime_internal"


def build_delta_rows(
    *,
    advisory_label: str,
    records: list[dict[str, str]],
    max_items: int = 8,
) -> list[dict[str, str]]:
    label = advisory_label.upper()
    if not supports_label(label):
        return []

    rows: list[DeltaRow] = []
    seen_keys: set[tuple[str, str, str]] = set()
    for record in records:
        path = str(record.get("path", "")).strip()
        if not path or path in {"<unknown>", "diff context"}:
            continue
        rule = str(record.get("rule", "")).strip() or "changed_file_path"
        snippet = str(record.get("snippet", "")).strip()
        before = str(record.get("before", "")).strip()
        after = str(record.get("after", "")).strip()
        line_span = str(record.get("line_span", "")).strip() or None
        action = _derive_delta_action(rule=rule, snippet=snippet)
        if before and after and before != after and action == "modified":
            action = "changed"
        if before and after and before == after and action != "unchanged":
            action = "unchanged"
        target = _derive_delta_target(rule=rule, snippet=snippet)
        key = (path, action, target)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        rows.append(
            DeltaRow(
                path=path,
                line_span=line_span,
                rule=rule,
                action=action,
                target=target,
                impact_scope=_derive_impact_scope(path=path, rule=rule),
                suggested_bump=label,
                severity=str(record.get("severity", label)).strip().upper() or label,
                before=before or None,
                after=after or None,
                impact_reason=str(record.get("impact_reason", "")).strip() or None,
            )
        )

    ranked = sorted(
        rows,
        key=lambda item: (
            -_severity_rank(item.severity),
            item.path,
            item.rule,
            item.target,
            -_action_priority(item.action),
        ),
    )
    return [item.to_dict() for item in ranked[:max_items]]


def render_reasoning_from_facts(facts: ExplanationFacts) -> str | None:
    label = facts.label.upper()
    if label == "MAJOR":
        text = f"Court selected MAJOR because breaking behavior changed in {facts.target_summary}"
        if facts.operation_hint:
            text += f", including {facts.operation_hint}"
        return text + "."
    if label == "MINOR":
        text = f"Court selected MINOR because backward-compatible behavior was added in {facts.target_summary}"
        if facts.operation_hint:
            text += f", including {facts.operation_hint}"
        return text + "."
    if label == "PATCH":
        text = (
            f"Court selected PATCH because internal behavior was updated in {facts.target_summary}"
        )
        if facts.operation_hint:
            text += f", including {facts.operation_hint}"
        return text + "."
    if label == "NO_BUMP":
        return (
            f"Court selected NO_BUMP because operational-only changes were detected "
            f"in {facts.target_summary}."
        )
    return None


def render_changelog_from_facts(facts: ExplanationFacts) -> str | None:
    label = facts.label.upper()
    if label == "MAJOR":
        text = f"feat({facts.scope})!: introduce breaking behavior across {facts.target_summary}"
        if facts.operation_hint:
            text += f" via {facts.operation_hint}"
        return text
    if label == "MINOR":
        text = f"feat({facts.scope}): add behavior across {facts.target_summary}"
        if facts.operation_hint:
            text += f" via {facts.operation_hint}"
        return text
    if label == "PATCH":
        text = f"fix({facts.scope}): update behavior across {facts.target_summary}"
        if facts.operation_hint:
            text += f" via {facts.operation_hint}"
        return text
    if label == "NO_BUMP":
        return "chore: no release required"
    return None


def passes_quality_policy(text: str) -> bool:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return False
    if MARKER_TOKEN_PATTERN.search(normalized):
        return False
    if CONSTANT_LEAK_PATTERN.search(normalized):
        return False
    return not (normalized.startswith(('r"', "r'")) or "\\b" in normalized)
