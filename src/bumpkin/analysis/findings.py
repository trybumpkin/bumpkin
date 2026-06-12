from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

SEVERITY_ORDER = {
    "NO_BUMP": 0,
    "PATCH": 1,
    "MINOR": 2,
    "MAJOR": 3,
}
CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}

JS_TS_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts")
PYTHON_EXTENSIONS = (".py",)
DIFF_GIT_HEADER = re.compile(r"^diff --git a/(.+?) b/(.+)$")
REQUIRES_PYTHON_PATTERN = re.compile(
    r"""requires-python\s*=\s*["']>=\s*(\d+(?:\.\d+)*)[^"']*["']""",
    re.IGNORECASE,
)

EXPORT_DECL_PATTERNS = [
    re.compile(r"\bexport\s+(?:declare\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"\bexport\s+(?:declare\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"\bexport\s+(?:declare\s+)?(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"\bexport\s+(?:declare\s+)?(?:interface|type|enum)\s+([A-Za-z_][A-Za-z0-9_]*)"),
]

EXPORT_FUNCTION_SIGNATURE_PATTERNS = [
    re.compile(
        r"\bexport\s+(?:declare\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*"
        r"\(([^)]*)\)\s*(?::\s*([^{=]+?))?\s*(?:\{|$)"
    ),
    re.compile(
        r"\bexport\s+(?:declare\s+)?(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
        r"(?:async\s*)?\(([^)]*)\)\s*(?::\s*([^=]+?))?\s*=>"
    ),
]
PYTHON_PUBLIC_DEF_PATTERN = re.compile(
    r"\b(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*(?:->\s*([^:]+))?:"
)
PYTHON_DEF_START_PATTERN = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
PYTHON_PUBLIC_CLASS_PATTERN = re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\b")
PYTHON_ALL_EXPORT_START_PATTERN = re.compile(r"^\s*__all__\s*=\s*")
PYTHON_PUBLIC_ASSIGNMENT_PATTERN = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?::\s*[^=]+)?=\s*.+$"
)


@dataclass(frozen=True)
class Finding:
    id: str
    severity: str
    rule: str
    confidence: str
    title: str
    why: str
    evidence: list[dict[str, str]]
    suggested_bump: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "severity": self.severity,
            "rule": self.rule,
            "confidence": self.confidence,
            "title": self.title,
            "why": self.why,
            "evidence": self.evidence,
            "suggested_bump": self.suggested_bump,
        }


@dataclass(frozen=True)
class AggregatedFindingResult:
    status: str
    label: str | None
    confidence: str | None
    reasoning: str
    changelog: str | None
    aggregation_trace: str
    contributing_findings: int

    def to_result_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "label": self.label,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "changelog": self.changelog,
        }


@dataclass
class _FileDiff:
    path: str
    removed_lines: list[str]
    added_lines: list[str]
    context_lines: list[str]
    ordered_lines: list[tuple[str, str]]
    touched_export_markers: bool


@dataclass(frozen=True)
class _FunctionSignature:
    name: str
    params: str
    return_type: str | None
    source: str


def _signatures_equivalent(left: _FunctionSignature, right: _FunctionSignature) -> bool:
    return left.params == right.params and left.return_type == right.return_type


def _match_export_renames(
    *,
    removed_only: list[str],
    added_only: list[str],
    removed_signatures: dict[str, list[_FunctionSignature]],
    added_signatures: dict[str, list[_FunctionSignature]],
) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    used_added: set[str] = set()
    for old_name in removed_only:
        old_sigs = removed_signatures.get(old_name, [])
        if not old_sigs:
            continue
        for new_name in added_only:
            if new_name in used_added:
                continue
            new_sigs = added_signatures.get(new_name, [])
            if not new_sigs:
                continue
            equivalent = any(
                _signatures_equivalent(old_sig, new_sig)
                for old_sig in old_sigs
                for new_sig in new_sigs
            )
            if not equivalent:
                continue
            pairs.append((old_name, new_name))
            used_added.add(new_name)
            break
    return pairs


def _is_js_ts_path(path: str) -> bool:
    normalized = path.strip().lower()
    return normalized.endswith(JS_TS_EXTENSIONS)


def _is_python_path(path: str) -> bool:
    normalized = path.strip().lower()
    return normalized.endswith(PYTHON_EXTENSIONS)


def _is_root_pyproject(path: str) -> bool:
    normalized = path.strip().replace("\\", "/").lower()
    return normalized == "pyproject.toml"


def _parse_diff_files(diff_text: str) -> list[_FileDiff]:
    file_diffs: list[_FileDiff] = []
    current: _FileDiff | None = None
    saw_header = False

    for raw in diff_text.splitlines():
        header = DIFF_GIT_HEADER.match(raw.strip())
        if header:
            saw_header = True
            if current is not None:
                file_diffs.append(current)
            current = _FileDiff(
                path=header.group(2),
                removed_lines=[],
                added_lines=[],
                context_lines=[],
                ordered_lines=[],
                touched_export_markers=False,
            )
            continue

        if current is None:
            continue
        if raw.startswith(("---", "+++", "@@", "index ")):
            continue
        if raw.startswith("-"):
            line = raw[1:].rstrip()
            if line.strip():
                current.removed_lines.append(line)
                current.ordered_lines.append(("-", line))
                if "export " in line:
                    current.touched_export_markers = True
        elif raw.startswith("+"):
            line = raw[1:].rstrip()
            if line.strip():
                current.added_lines.append(line)
                current.ordered_lines.append(("+", line))
                if "export " in line:
                    current.touched_export_markers = True
        elif raw.startswith(" "):
            line = raw[1:].rstrip()
            if line.strip():
                current.context_lines.append(line)
                current.ordered_lines.append((" ", line))

    if current is not None:
        file_diffs.append(current)

    if saw_header:
        return file_diffs

    # Fallback for synthetic diffs without git headers.
    removed: list[str] = []
    added: list[str] = []
    touched_export = False
    for raw in diff_text.splitlines():
        if raw.startswith(("---", "+++", "@@", "index ", "diff --git ")):
            continue
        if raw.startswith("-"):
            line = raw[1:].rstrip()
            if line.strip():
                removed.append(line)
                if "export " in line:
                    touched_export = True
        elif raw.startswith("+"):
            line = raw[1:].rstrip()
            if line.strip():
                added.append(line)
                if "export " in line:
                    touched_export = True
    if not removed and not added:
        return []
    return [
        _FileDiff(
            path="<unknown>.ts",
            removed_lines=removed,
            added_lines=added,
            context_lines=[],
            ordered_lines=[*[("-", line) for line in removed], *[("+", line) for line in added]],
            touched_export_markers=touched_export,
        )
    ]


def _extract_export_names(lines: list[str]) -> set[str]:
    exports: set[str] = set()
    for line in lines:
        for pattern in EXPORT_DECL_PATTERNS:
            match = pattern.search(line)
            if match:
                exports.add(match.group(1))
        if "export default" in line:
            exports.add("__default__")
        brace_export_match = re.search(r"\bexport\s*{\s*([^}]+)\s*}", line)
        if brace_export_match:
            members = [member.strip() for member in brace_export_match.group(1).split(",")]
            for member in members:
                if not member:
                    continue
                if " as " in member:
                    exports.add(member.split(" as ", 1)[1].strip())
                else:
                    exports.add(member)
    return exports


def _normalize_type(raw_type: str | None) -> str | None:
    if raw_type is None:
        return None
    cleaned = re.sub(r"\s+", " ", raw_type).strip()
    return cleaned or None


def _extract_export_signatures(lines: list[str]) -> dict[str, list[_FunctionSignature]]:
    signatures: dict[str, list[_FunctionSignature]] = {}
    for line in lines:
        for pattern in EXPORT_FUNCTION_SIGNATURE_PATTERNS:
            for match in pattern.finditer(line):
                signature = _FunctionSignature(
                    name=match.group(1),
                    params=re.sub(r"\s+", "", match.group(2)),
                    return_type=_normalize_type(match.group(3)),
                    source=line,
                )
                signatures.setdefault(signature.name, []).append(signature)
    return signatures


def _python_indent_level(line: str) -> int:
    expanded = line.expandtabs(8)
    return len(expanded) - len(expanded.lstrip(" "))


def _is_python_top_level_statement(line: str) -> bool:
    return _python_indent_level(line) == 0


def _iter_python_version_source_lines(
    file_diff: _FileDiff,
    *,
    target_prefix: str,
) -> list[str]:
    return [
        line
        for prefix, line in file_diff.ordered_lines
        if prefix in {" ", target_prefix}
    ]


def _collect_python_signature_source(lines: list[str], start_index: int) -> tuple[str, int]:
    collected = [lines[start_index]]
    paren_depth = lines[start_index].count("(") - lines[start_index].count(")")
    cursor = start_index + 1

    while cursor < len(lines):
        if paren_depth <= 0 and collected[-1].rstrip().endswith(":"):
            break
        collected.append(lines[cursor])
        paren_depth += lines[cursor].count("(") - lines[cursor].count(")")
        cursor += 1

    normalized = " ".join(line.strip() for line in collected)
    return normalized, cursor


def _collect_python_all_assignment(lines: list[str], start_index: int) -> tuple[str, int]:
    collected = [lines[start_index]]
    bracket_depth = (
        lines[start_index].count("[")
        + lines[start_index].count("(")
        - lines[start_index].count("]")
        - lines[start_index].count(")")
    )
    cursor = start_index + 1

    while cursor < len(lines):
        if bracket_depth <= 0:
            break
        collected.append(lines[cursor])
        bracket_depth += (
            lines[cursor].count("[")
            + lines[cursor].count("(")
            - lines[cursor].count("]")
            - lines[cursor].count(")")
        )
        cursor += 1

    normalized = " ".join(line.strip() for line in collected)
    return normalized, cursor


def _extract_python_all_contract(lines: list[str]) -> tuple[bool, set[str]]:
    exports: set[str] = set()
    has_explicit_all = False
    index = 0
    while index < len(lines):
        line = lines[index]
        if not _is_python_top_level_statement(line):
            index += 1
            continue
        if not PYTHON_ALL_EXPORT_START_PATTERN.search(line):
            index += 1
            continue
        has_explicit_all = True
        assignment_source, index = _collect_python_all_assignment(lines, index)
        members = re.findall(r"""['"]([A-Za-z_][A-Za-z0-9_]*)['"]""", assignment_source)
        exports.update(member for member in members if not member.startswith("_"))
    return has_explicit_all, exports


def _extract_python_public_names(lines: list[str]) -> set[str]:
    has_explicit_all, all_exports = _extract_python_all_contract(lines)
    if has_explicit_all:
        return all_exports

    exports: set[str] = set()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not _is_python_top_level_statement(line):
            index += 1
            continue
        def_start = PYTHON_DEF_START_PATTERN.search(line)
        if def_start:
            signature_source, index = _collect_python_signature_source(lines, index)
            def_match = PYTHON_PUBLIC_DEF_PATTERN.search(signature_source)
        else:
            def_match = None
        if def_match:
            name = def_match.group(1)
            params = _split_top_level_params(def_match.group(2))
            if name.startswith("_"):
                continue
            if params and params[0].strip() in {"self", "cls"}:
                continue
            exports.add(name)
            continue

        class_match = PYTHON_PUBLIC_CLASS_PATTERN.search(line)
        if class_match:
            name = class_match.group(1)
            if not name.startswith("_"):
                exports.add(name)
            index += 1
            continue

        assignment_match = PYTHON_PUBLIC_ASSIGNMENT_PATTERN.search(line)
        if assignment_match:
            name = assignment_match.group(1)
            if not name.startswith("_") and name != "__all__":
                exports.add(name)
        index += 1

    return exports


def _extract_python_all_exports(lines: list[str]) -> set[str]:
    return _extract_python_all_contract(lines)[1]


def _iter_python_version_lines(
    file_diff: _FileDiff,
    *,
    target_prefix: str,
) -> list[tuple[str, bool]]:
    active_prefixes = {" ", target_prefix}
    return [
        (line, prefix == target_prefix)
        for prefix, line in file_diff.ordered_lines
        if prefix in active_prefixes
    ]


def _collect_python_signature_block(
    version_lines: list[tuple[str, bool]],
    start_index: int,
) -> tuple[str, bool, int]:
    collected = [version_lines[start_index][0]]
    block_is_target = version_lines[start_index][1]
    paren_depth = collected[0].count("(") - collected[0].count(")")
    cursor = start_index + 1

    while cursor < len(version_lines):
        if paren_depth <= 0 and collected[-1].rstrip().endswith(":"):
            break
        line, is_target_line = version_lines[cursor]
        collected.append(line)
        block_is_target = block_is_target or is_target_line
        paren_depth += line.count("(") - line.count(")")
        cursor += 1

    normalized = " ".join(line.strip() for line in collected)
    return normalized, block_is_target, cursor


def _extract_python_signatures(
    file_diff: _FileDiff,
    *,
    target_prefix: str,
) -> dict[str, list[_FunctionSignature]]:
    signatures: dict[str, list[_FunctionSignature]] = {}
    current_top_level_class: str | None = None
    version_lines = _iter_python_version_lines(file_diff, target_prefix=target_prefix)
    index = 0

    while index < len(version_lines):
        line, _is_target_line = version_lines[index]
        is_top_level = _is_python_top_level_statement(line)
        class_match = PYTHON_PUBLIC_CLASS_PATTERN.search(line) if is_top_level else None
        if class_match and not line.lstrip().startswith("@"):
            class_name = class_match.group(1)
            current_top_level_class = class_name if not class_name.startswith("_") else None
            index += 1
            continue

        if is_top_level and not class_match:
            current_top_level_class = None

        def_start = PYTHON_DEF_START_PATTERN.search(line)
        if not def_start:
            index += 1
            continue
        signature_source, block_is_target, index = _collect_python_signature_block(
            version_lines,
            index,
        )
        def_match = PYTHON_PUBLIC_DEF_PATTERN.search(signature_source)
        if not def_match or not block_is_target:
            continue

        name = def_match.group(1)
        params = re.sub(r"\s+", "", def_match.group(2))
        return_type = _normalize_type(def_match.group(3))
        param_list = _split_top_level_params(def_match.group(2))
        if (
            name == "__init__"
            and current_top_level_class
            and param_list
            and param_list[0].strip() == "self"
            and _python_indent_level(line) > 0
        ):
            symbol_name = f"{current_top_level_class}.__init__"
        else:
            if name.startswith("_"):
                continue
            if not is_top_level:
                continue
            if param_list and param_list[0].strip() in {"self", "cls"}:
                continue
            symbol_name = name

        signature = _FunctionSignature(
            name=symbol_name,
            params=params,
            return_type=return_type,
            source=signature_source,
        )
        signatures.setdefault(symbol_name, []).append(signature)

    return signatures


def _extract_python_classes(
    lines: list[str],
    *,
    has_explicit_all: bool = False,
    explicit_exports: set[str] | None = None,
) -> set[str]:
    classes: set[str] = set()
    for line in lines:
        if not _is_python_top_level_statement(line):
            continue
        match = PYTHON_PUBLIC_CLASS_PATTERN.search(line)
        if not match:
            continue
        name = match.group(1)
        if name.startswith("_"):
            continue
        if has_explicit_all and explicit_exports is not None and name not in explicit_exports:
            continue
        if not name.startswith("_"):
            classes.add(name)
    return classes


def _extract_requires_python_floor(lines: list[str]) -> tuple[int, ...] | None:
    for line in lines:
        match = REQUIRES_PYTHON_PATTERN.search(line)
        if not match:
            continue
        return tuple(int(part) for part in match.group(1).split("."))
    return None


def _split_top_level_params(params: str) -> list[str]:
    text = params.strip()
    if not text:
        return []

    pieces: list[str] = []
    current: list[str] = []
    stack: list[str] = []
    opens = {"(": ")", "[": "]", "{": "}", "<": ">"}
    closes = {value: key for key, value in opens.items()}

    for char in text:
        if char == "," and not stack:
            token = "".join(current).strip()
            if token:
                pieces.append(token)
            current = []
            continue
        current.append(char)
        if char in opens:
            stack.append(char)
        elif char in closes and stack and stack[-1] == closes[char]:
            stack.pop()

    token = "".join(current).strip()
    if token:
        pieces.append(token)
    return pieces


def _is_optional_param(token: str) -> bool:
    value = token.strip()
    if not value:
        return False
    if value.startswith("..."):
        return True
    if "=" in value:
        return True
    left = value.split(":", 1)[0]
    return left.endswith("?")


def _is_optional_widening(old_params: str, new_params: str) -> bool:
    old_list = _split_top_level_params(old_params)
    new_list = _split_top_level_params(new_params)
    if len(new_list) < len(old_list):
        return False
    if new_list[: len(old_list)] != old_list:
        return False
    extras = new_list[len(old_list) :]
    if not extras:
        return False
    return all(_is_optional_param(param) for param in extras)


def _is_requiredness_tightening(old_params: str, new_params: str) -> bool:
    old_list = _split_top_level_params(old_params)
    new_list = _split_top_level_params(new_params)
    if len(new_list) < len(old_list):
        return True

    for index, old_token in enumerate(old_list):
        if index >= len(new_list):
            return True
        new_token = new_list[index]
        if old_token == new_token:
            continue
        if _is_optional_param(old_token) and not _is_optional_param(new_token):
            return True
        return True

    if len(new_list) > len(old_list):
        extras = new_list[len(old_list) :]
        return not all(_is_optional_param(param) for param in extras)

    return False


def _confidence_for_findings(findings: list[Finding], severity: str) -> str:
    ranked = [
        CONFIDENCE_ORDER.get(finding.confidence, 0)
        for finding in findings
        if finding.severity == severity
    ]
    if not ranked:
        return "low"
    # Conservative confidence: one weak contributing finding lowers confidence.
    min_rank = min(ranked)
    for label, rank in CONFIDENCE_ORDER.items():
        if rank == min_rank:
            return label
    return "low"


def _summary_counts(findings: list[Finding]) -> str:
    counts = {"MAJOR": 0, "MINOR": 0, "PATCH": 0, "NO_BUMP": 0, "MANUAL_REVIEW": 0}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    return (
        f"MAJOR={counts['MAJOR']}, MINOR={counts['MINOR']}, PATCH={counts['PATCH']}, "
        f"NO_BUMP={counts['NO_BUMP']}, MANUAL_REVIEW={counts['MANUAL_REVIEW']}"
    )


def aggregate_findings(findings: list[Finding]) -> AggregatedFindingResult | None:
    if not findings:
        return None

    severities = {finding.severity for finding in findings}
    counts_text = _summary_counts(findings)

    if "MAJOR" in severities:
        label = "MAJOR"
        trace = "MAJOR findings present; selected MAJOR."
    elif "MINOR" in severities:
        label = "MINOR"
        trace = "No MAJOR findings; MINOR findings present; selected MINOR."
    elif "PATCH" in severities:
        label = "PATCH"
        trace = "No MAJOR/MINOR findings; PATCH findings present; selected PATCH."
    elif "NO_BUMP" in severities:
        label = "NO_BUMP"
        trace = "Only NO_BUMP findings present; selected NO_BUMP."
    else:
        return AggregatedFindingResult(
            status="manual_review",
            label=None,
            confidence=None,
            reasoning=(
                "Deterministic findings could not produce an authoritative SemVer bump. "
                f"Finding counts: {counts_text}."
            ),
            changelog=None,
            aggregation_trace="No deterministic bump severity found; manual review required.",
            contributing_findings=len(findings),
        )

    changelog = {
        "MAJOR": "feat: introduce breaking api changes",
        "MINOR": "feat: add backward-compatible api changes",
        "PATCH": "fix: update internal implementation",
        "NO_BUMP": "chore: no release required",
    }[label]
    confidence = _confidence_for_findings(findings, label)
    return AggregatedFindingResult(
        status="classified",
        label=label,
        confidence=confidence,
        reasoning=(
            "Deterministic JS/TS exported API analysis produced findings with counts: "
            f"{counts_text}."
        ),
        changelog=changelog,
        aggregation_trace=trace,
        contributing_findings=len(findings),
    )


def _build_finding(
    *,
    severity: str,
    rule: str,
    confidence: str,
    title: str,
    why: str,
    path: str,
    snippet: str,
    counter: int,
) -> Finding:
    suggested = severity if severity != "MANUAL_REVIEW" else None
    return Finding(
        id=f"{rule}:{counter}",
        severity=severity,
        rule=rule,
        confidence=confidence,
        title=title,
        why=why,
        evidence=[{"path": path, "snippet": snippet[:180]}],
        suggested_bump=suggested,
    )


def detect_js_ts_export_findings(diff_text: str) -> list[Finding]:
    file_diffs = _parse_diff_files(diff_text)
    findings: list[Finding] = []
    counter = 0

    for file_diff in file_diffs:
        if not _is_js_ts_path(file_diff.path):
            continue

        start_count = len(findings)
        removed_exports = _extract_export_names(file_diff.removed_lines)
        added_exports = _extract_export_names(file_diff.added_lines)
        removed_signatures = _extract_export_signatures(file_diff.removed_lines)
        added_signatures = _extract_export_signatures(file_diff.added_lines)

        removed_only = sorted(removed_exports - added_exports)
        added_only = sorted(added_exports - removed_exports)
        rename_pairs = _match_export_renames(
            removed_only=removed_only,
            added_only=added_only,
            removed_signatures=removed_signatures,
            added_signatures=added_signatures,
        )
        renamed_removed = {old_name for old_name, _ in rename_pairs}
        renamed_added = {new_name for _, new_name in rename_pairs}

        for old_name, new_name in rename_pairs:
            counter += 1
            evidence = f"{old_name} -> {new_name}"
            findings.append(
                _build_finding(
                    severity="MAJOR",
                    rule="export_symbol_renamed",
                    confidence="high",
                    title=f"Renamed exported symbol: {old_name} -> {new_name}",
                    why=(
                        "Renaming an exported symbol removes the old public API name and "
                        "breaks existing imports."
                    ),
                    path=file_diff.path,
                    snippet=evidence,
                    counter=counter,
                )
            )

        removed_only = [symbol for symbol in removed_only if symbol not in renamed_removed]
        if removed_only:
            counter += 1
            findings.append(
                _build_finding(
                    severity="MAJOR",
                    rule="export_symbol_removed",
                    confidence="high",
                    title=f"Removed exported symbol(s): {', '.join(removed_only[:3])}",
                    why="Removing exported API symbols is a breaking public API change.",
                    path=file_diff.path,
                    snippet=next(
                        (
                            line
                            for line in file_diff.removed_lines
                            if any(symbol in line for symbol in removed_only)
                        ),
                        file_diff.removed_lines[0] if file_diff.removed_lines else "",
                    ),
                    counter=counter,
                )
            )

        added_only = [symbol for symbol in added_only if symbol not in renamed_added]
        if added_only:
            counter += 1
            findings.append(
                _build_finding(
                    severity="MINOR",
                    rule="export_symbol_added",
                    confidence="high",
                    title=f"Added exported symbol(s): {', '.join(added_only[:3])}",
                    why="Adding exported API symbols is a backward-compatible API expansion.",
                    path=file_diff.path,
                    snippet=next(
                        (
                            line
                            for line in file_diff.added_lines
                            if any(symbol in line for symbol in added_only)
                        ),
                        file_diff.added_lines[0] if file_diff.added_lines else "",
                    ),
                    counter=counter,
                )
            )

        shared_exports = sorted(removed_exports & added_exports)

        for symbol in shared_exports:
            old_sigs = removed_signatures.get(symbol, [])
            new_sigs = added_signatures.get(symbol, [])
            if not old_sigs or not new_sigs:
                continue

            old_params = old_sigs[0].params
            new_params = new_sigs[0].params
            old_return = old_sigs[0].return_type
            new_return = new_sigs[0].return_type

            if old_params == new_params and old_return == new_return:
                continue

            if _is_optional_widening(old_params, new_params):
                counter += 1
                findings.append(
                    _build_finding(
                        severity="MINOR",
                        rule="export_signature_optional_widening",
                        confidence="medium",
                        title=f"Backward-compatible signature widening: {symbol}",
                        why=(
                            "An exported function added only optional parameters, which is "
                            "backward compatible for existing callers."
                        ),
                        path=file_diff.path,
                        snippet=new_sigs[0].source,
                        counter=counter,
                    )
                )
                continue

            if _is_requiredness_tightening(old_params, new_params):
                counter += 1
                findings.append(
                    _build_finding(
                        severity="MAJOR",
                        rule="export_signature_requiredness_tightening",
                        confidence="high",
                        title=f"Breaking signature tightening: {symbol}",
                        why=(
                            "The exported function signature became stricter "
                            "(removed/required parameter changes), which can break callers."
                        ),
                        path=file_diff.path,
                        snippet=new_sigs[0].source,
                        counter=counter,
                    )
                )
                continue

            if old_return and new_return and old_return != new_return:
                counter += 1
                findings.append(
                    _build_finding(
                        severity="MAJOR",
                        rule="export_return_type_changed",
                        confidence="medium",
                        title=f"Exported return type changed: {symbol}",
                        why=(
                            "Changing an exported return type can break downstream consumers "
                            "expecting the previous contract."
                        ),
                        path=file_diff.path,
                        snippet=new_sigs[0].source,
                        counter=counter,
                    )
                )
                continue

            counter += 1
            findings.append(
                _build_finding(
                    severity="MAJOR",
                    rule="export_signature_incompatible_change",
                    confidence="medium",
                    title=f"Incompatible exported signature change: {symbol}",
                    why=(
                        "The exported API signature changed in a way that is not clearly "
                        "backward compatible."
                    ),
                    path=file_diff.path,
                    snippet=new_sigs[0].source,
                    counter=counter,
                )
            )

        if len(findings) == start_count and file_diff.touched_export_markers and shared_exports:
            unchanged_shared_signatures = True
            for symbol in shared_exports:
                old_sigs = removed_signatures.get(symbol, [])
                new_sigs = added_signatures.get(symbol, [])
                if not old_sigs or not new_sigs:
                    unchanged_shared_signatures = False
                    break
                if old_sigs[0].params != new_sigs[0].params:
                    unchanged_shared_signatures = False
                    break
                if old_sigs[0].return_type != new_sigs[0].return_type:
                    unchanged_shared_signatures = False
                    break
            if unchanged_shared_signatures:
                counter += 1
                findings.append(
                    _build_finding(
                        severity="PATCH",
                        rule="export_behavior_change_no_signature_delta",
                        confidence="medium",
                        title="Exported behavior changed without API signature change",
                        why=(
                            "The exported symbol remains present with the same signature, "
                            "so this is treated as a patch-level behavior change."
                        ),
                        path=file_diff.path,
                        snippet=file_diff.added_lines[0] if file_diff.added_lines else "",
                        counter=counter,
                    )
                )

        if len(findings) == start_count and file_diff.touched_export_markers:
            counter += 1
            snippet = (
                file_diff.added_lines[0]
                if file_diff.added_lines
                else (file_diff.removed_lines[0] if file_diff.removed_lines else "export change")
            )
            findings.append(
                _build_finding(
                    severity="MANUAL_REVIEW",
                    rule="export_change_unclassified",
                    confidence="low",
                    title="Export change requires manual review",
                    why=(
                        "Export markers changed but deterministic rules could not infer a "
                        "safe SemVer classification."
                    ),
                    path=file_diff.path,
                    snippet=snippet,
                    counter=counter,
                )
            )

    return findings


def detect_python_api_findings(diff_text: str) -> list[Finding]:
    file_diffs = _parse_diff_files(diff_text)
    findings: list[Finding] = []
    counter = 0

    for file_diff in file_diffs:
        removed_floor = _extract_requires_python_floor(file_diff.removed_lines)
        added_floor = _extract_requires_python_floor(file_diff.added_lines)
        if (
            _is_root_pyproject(file_diff.path)
            and removed_floor is not None
            and added_floor is not None
            and added_floor > removed_floor
        ):
            counter += 1
            findings.append(
                _build_finding(
                    severity="MAJOR",
                    rule="python_requires_floor_raised",
                    confidence="high",
                    title=(
                        "Raised supported Python floor: "
                        f"{'.'.join(map(str, removed_floor))} -> {'.'.join(map(str, added_floor))}"
                    ),
                    why=(
                        "Raising the minimum supported Python version is a breaking compatibility "
                        "change for downstream users on older runtimes."
                    ),
                    path=file_diff.path,
                    snippet=next(
                        (
                            line
                            for line in file_diff.added_lines
                            if "requires-python" in line.lower()
                        ),
                        file_diff.added_lines[0] if file_diff.added_lines else "",
                    ),
                    counter=counter,
                )
            )
            continue

        if not _is_python_path(file_diff.path):
            continue

        start_count = len(findings)
        removed_version_lines = _iter_python_version_source_lines(file_diff, target_prefix="-")
        added_version_lines = _iter_python_version_source_lines(file_diff, target_prefix="+")
        removed_has_explicit_all, removed_all_exports = _extract_python_all_contract(
            removed_version_lines
        )
        added_has_explicit_all, added_all_exports = _extract_python_all_contract(
            added_version_lines
        )
        removed_exports = (
            removed_all_exports
            if removed_has_explicit_all
            else _extract_python_public_names(removed_version_lines)
        )
        added_exports = (
            added_all_exports
            if added_has_explicit_all
            else _extract_python_public_names(added_version_lines)
        )
        removed_signatures = _extract_python_signatures(file_diff, target_prefix="-")
        added_signatures = _extract_python_signatures(file_diff, target_prefix="+")
        removed_classes = _extract_python_classes(
            removed_version_lines,
            has_explicit_all=removed_has_explicit_all,
            explicit_exports=removed_all_exports,
        )
        added_classes = _extract_python_classes(
            added_version_lines,
            has_explicit_all=added_has_explicit_all,
            explicit_exports=added_all_exports,
        )

        removed_only = sorted(removed_exports - added_exports)
        added_only = sorted(added_exports - removed_exports)
        rename_pairs = _match_export_renames(
            removed_only=removed_only,
            added_only=added_only,
            removed_signatures=removed_signatures,
            added_signatures=added_signatures,
        )
        renamed_removed = {old_name for old_name, _ in rename_pairs}
        renamed_added = {new_name for _, new_name in rename_pairs}

        for old_name, new_name in rename_pairs:
            counter += 1
            findings.append(
                _build_finding(
                    severity="MAJOR",
                    rule="export_symbol_renamed",
                    confidence="high",
                    title=f"Renamed public Python symbol: {old_name} -> {new_name}",
                    why=(
                        "Renaming a public Python symbol removes the previous import path for "
                        "downstream users."
                    ),
                    path=file_diff.path,
                    snippet=f"{old_name} -> {new_name}",
                    counter=counter,
                )
            )

        removed_only = [symbol for symbol in removed_only if symbol not in renamed_removed]
        if removed_only:
            counter += 1
            findings.append(
                _build_finding(
                    severity="MAJOR",
                    rule="export_symbol_removed",
                    confidence="high",
                    title=f"Removed public Python symbol(s): {', '.join(removed_only[:3])}",
                    why="Removing public Python API symbols is a breaking change for importers.",
                    path=file_diff.path,
                    snippet=next(
                        (
                            line
                            for line in file_diff.removed_lines
                            if any(symbol in line for symbol in removed_only)
                        ),
                        file_diff.removed_lines[0] if file_diff.removed_lines else "",
                    ),
                    counter=counter,
                )
            )

        added_only = [symbol for symbol in added_only if symbol not in renamed_added]
        if added_only:
            counter += 1
            findings.append(
                _build_finding(
                    severity="MINOR",
                    rule="export_symbol_added",
                    confidence="high",
                    title=f"Added public Python symbol(s): {', '.join(added_only[:3])}",
                    why="Adding public Python API symbols expands the supported surface area.",
                    path=file_diff.path,
                    snippet=next(
                        (
                            line
                            for line in file_diff.added_lines
                            if any(symbol in line for symbol in added_only)
                        ),
                        file_diff.added_lines[0] if file_diff.added_lines else "",
                    ),
                    counter=counter,
                )
            )

        shared_public_exports = removed_exports & added_exports
        shared_symbols = sorted(
            symbol
            for symbol in (set(removed_signatures) & set(added_signatures))
            if symbol in shared_public_exports
            or (
                symbol.endswith(".__init__")
                and symbol.rsplit(".", 1)[0] in shared_public_exports
            )
        )
        for symbol in shared_symbols:
            old_sigs = removed_signatures.get(symbol, [])
            new_sigs = added_signatures.get(symbol, [])
            if not old_sigs or not new_sigs:
                continue

            old_params = old_sigs[0].params
            new_params = new_sigs[0].params
            old_return = old_sigs[0].return_type
            new_return = new_sigs[0].return_type

            if old_params == new_params and old_return == new_return:
                continue

            if _is_optional_widening(old_params, new_params):
                counter += 1
                findings.append(
                    _build_finding(
                        severity="MINOR",
                        rule="export_signature_optional_widening",
                        confidence="medium",
                        title=f"Backward-compatible Python signature widening: {symbol}",
                        why=(
                            "The public Python callable added only optional parameters, which "
                            "should remain backward compatible."
                        ),
                        path=file_diff.path,
                        snippet=new_sigs[0].source,
                        counter=counter,
                    )
                )
                continue

            if _is_requiredness_tightening(old_params, new_params):
                counter += 1
                findings.append(
                    _build_finding(
                        severity="MAJOR",
                        rule="export_signature_requiredness_tightening",
                        confidence="high",
                        title=f"Breaking Python signature tightening: {symbol}",
                        why=(
                            "The public Python callable became stricter by adding required input "
                            "or tightening existing parameters."
                        ),
                        path=file_diff.path,
                        snippet=new_sigs[0].source,
                        counter=counter,
                    )
                )
                continue

            if old_return and new_return and old_return != new_return:
                counter += 1
                findings.append(
                    _build_finding(
                        severity="MAJOR",
                        rule="export_return_type_changed",
                        confidence="medium",
                        title=f"Public Python return type changed: {symbol}",
                        why=(
                            "Changing the declared return contract of a public Python callable can "
                            "break consumers and typing expectations."
                        ),
                        path=file_diff.path,
                        snippet=new_sigs[0].source,
                        counter=counter,
                    )
                )
                continue

            counter += 1
            findings.append(
                _build_finding(
                    severity="MAJOR",
                    rule="export_signature_incompatible_change",
                    confidence="medium",
                    title=f"Incompatible public Python signature change: {symbol}",
                    why=(
                        "The public Python callable changed in a way that is not clearly backward "
                        "compatible."
                    ),
                    path=file_diff.path,
                    snippet=new_sigs[0].source,
                    counter=counter,
                )
            )

        if len(findings) == start_count:
            removed_only_classes = sorted(removed_classes - added_classes)
            added_only_classes = sorted(added_classes - removed_classes)
            if removed_only_classes:
                counter += 1
                findings.append(
                    _build_finding(
                        severity="MAJOR",
                        rule="export_symbol_removed",
                        confidence="high",
                        title=f"Removed public Python class(es): {', '.join(removed_only_classes[:3])}",
                        why="Removing a public Python class is a breaking API change.",
                        path=file_diff.path,
                        snippet=next(
                            (
                                line
                                for line in file_diff.removed_lines
                                if any(symbol in line for symbol in removed_only_classes)
                            ),
                            file_diff.removed_lines[0] if file_diff.removed_lines else "",
                        ),
                        counter=counter,
                    )
                )
            elif added_only_classes:
                counter += 1
                findings.append(
                    _build_finding(
                        severity="MINOR",
                        rule="export_symbol_added",
                        confidence="high",
                        title=f"Added public Python class(es): {', '.join(added_only_classes[:3])}",
                        why="Adding a public Python class expands the available API surface.",
                        path=file_diff.path,
                        snippet=next(
                            (
                                line
                                for line in file_diff.added_lines
                                if any(symbol in line for symbol in added_only_classes)
                            ),
                            file_diff.added_lines[0] if file_diff.added_lines else "",
                        ),
                        counter=counter,
                    )
                )

    return findings


def detect_semver_findings(diff_text: str) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(detect_js_ts_export_findings(diff_text))
    findings.extend(detect_python_api_findings(diff_text))
    return findings
