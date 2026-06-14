from __future__ import annotations

import ast
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

SEVERITY_ORDER = {
    "NO_BUMP": 0,
    "PATCH": 1,
    "MINOR": 2,
    "MAJOR": 3,
}
CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}

JS_TS_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts")
PYTHON_EXTENSIONS = (".py", ".pyi")
DIFF_GIT_HEADER = re.compile(r"^diff --git a/(.+?) b/(.+)$")
REQUIRES_PYTHON_PATTERN = re.compile(
    r"""^\s*requires-python\s*=\s*["']>=\s*(\d+(?:\.\d+)*)[^"']*["']""",
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
PYTHON_ALL_EXPORT_START_PATTERN = re.compile(r"^\s*__all__(?:\s*:\s*[^=]+)?\s*(\+?=)\s*")
PYTHON_PUBLIC_ASSIGNMENT_PATTERN = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?::\s*[^=]+)?=\s*.+$"
)
PYTHON_IMPORT_START_PATTERN = re.compile(r"^\s*(?:from\b.+\bimport\b|import\b)")
PYTHON_TYPE_CHECKING_PATTERN = re.compile(r"^\s*if\s+(?:typing\.)?TYPE_CHECKING\s*:\s*$")


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


@dataclass(frozen=True)
class _PythonAllContract:
    has_explicit: bool
    is_supported: bool
    exports: set[str]


@dataclass(frozen=True)
class _PythonParameterSpec:
    name: str
    kind: str
    required: bool
    annotation: str | None


def _signatures_equivalent(left: _FunctionSignature, right: _FunctionSignature) -> bool:
    return left.params == right.params and left.return_type == right.return_type


def _signature_key(signature: _FunctionSignature) -> tuple[str, str | None]:
    return (signature.params, signature.return_type)


def _reindex_findings(findings: list[Finding]) -> list[Finding]:
    return [
        replace(finding, id=f"{finding.rule}:{index}") for index, finding in enumerate(findings, 1)
    ]


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


def _is_python_reexport_surface(path: str) -> bool:
    normalized = path.strip().replace("\\", "/").lower()
    return normalized == "__init__.py" or normalized.endswith("/__init__.py")


def _read_workspace_python_lines(path: str) -> list[str] | None:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = Path.cwd() / resolved
    try:
        return resolved.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None


def _python_package_root(path: str) -> str | None:
    normalized = path.strip().replace("\\", "/").strip("/")
    if not normalized:
        return None
    parts = normalized.split("/")
    if len(parts) < 2:
        return None
    package_parts = parts[:-1]
    if parts[0] == "src" and len(parts) >= 3:
        package_parts = parts[1:-1]
    if not package_parts:
        return None
    package_root = ".".join(package_parts)
    return package_root or None


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
    return [line for prefix, line in file_diff.ordered_lines if prefix in {" ", target_prefix}]


def _collect_python_signature_source(lines: list[str], start_index: int) -> tuple[str, int]:
    collected = [lines[start_index]]
    paren_depth = lines[start_index].count("(") - lines[start_index].count(")")
    cursor = start_index + 1

    while cursor < len(lines):
        stripped = collected[-1].strip()
        if paren_depth <= 0 and (
            stripped.endswith(":")
            or re.search(r"^\s*(?:async\s+)?def\b.*:\s*(?:\.\.\.|pass\b.*|return\b.*)$", stripped)
        ):
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
        + lines[start_index].count("{")
        - lines[start_index].count("]")
        - lines[start_index].count(")")
        - lines[start_index].count("}")
    )
    cursor = start_index + 1

    while cursor < len(lines):
        if bracket_depth <= 0:
            break
        collected.append(lines[cursor])
        bracket_depth += (
            lines[cursor].count("[")
            + lines[cursor].count("(")
            + lines[cursor].count("{")
            - lines[cursor].count("]")
            - lines[cursor].count(")")
            - lines[cursor].count("}")
        )
        cursor += 1

    normalized = " ".join(line.strip() for line in collected)
    return normalized, cursor


def _collect_python_import_statement(lines: list[str], start_index: int) -> tuple[str, int]:
    collected = [lines[start_index]]
    paren_depth = lines[start_index].count("(") - lines[start_index].count(")")
    cursor = start_index + 1

    while cursor < len(lines):
        if paren_depth <= 0 and not collected[-1].rstrip().endswith("\\"):
            break
        collected.append(lines[cursor])
        paren_depth += lines[cursor].count("(") - lines[cursor].count(")")
        cursor += 1

    normalized = " ".join(line.strip() for line in collected)
    return normalized, cursor


def _extract_python_string_names(node: ast.AST | None) -> tuple[bool, set[str]]:
    if node is None:
        return False, set()
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True, {node.value}
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        exports: set[str] = set()
        for element in node.elts:
            supported, nested = _extract_python_string_names(element)
            if not supported:
                return False, set()
            exports.update(nested)
        return True, exports
    return False, set()


def _extract_python_imported_names(statement_source: str, *, path: str) -> set[str]:
    try:
        module = ast.parse(statement_source)
    except SyntaxError:
        return set()
    if len(module.body) != 1:
        return set()

    statement = module.body[0]
    exports: set[str] = set()
    package_root = _python_package_root(path)
    if isinstance(statement, ast.ImportFrom) and _is_python_public_reexport_statement(
        statement,
        path=path,
    ):
        for alias in statement.names:
            if alias.name == "*":
                continue
            exported_name = alias.asname or alias.name
            if not exported_name.startswith("_"):
                exports.add(exported_name)
    elif isinstance(statement, ast.Import):
        for alias in statement.names:
            if (
                alias.asname is None
                or package_root is None
                or not (alias.name == package_root or alias.name.startswith(f"{package_root}."))
            ):
                continue
            exported_name = alias.asname
            if not exported_name.startswith("_"):
                exports.add(exported_name)
    return exports


def _extract_python_explicit_import_alias_names(statement_source: str, *, path: str) -> set[str]:
    try:
        module = ast.parse(statement_source)
    except SyntaxError:
        return set()
    if len(module.body) != 1:
        return set()

    statement = module.body[0]
    exports: set[str] = set()
    if isinstance(statement, ast.ImportFrom) and _is_python_public_reexport_statement(
        statement,
        path=path,
    ):
        for alias in statement.names:
            if alias.name == "*" or alias.asname is None:
                continue
            if not alias.asname.startswith("_"):
                exports.add(alias.asname)
    elif isinstance(statement, ast.Import):
        package_root = _python_package_root(path)
        for alias in statement.names:
            if (
                alias.asname is None
                or package_root is None
                or not (alias.name == package_root or alias.name.startswith(f"{package_root}."))
            ):
                continue
            if not alias.asname.startswith("_"):
                exports.add(alias.asname)
    return exports


def _is_python_public_reexport_statement(statement: ast.stmt, *, path: str) -> bool:
    package_root = _python_package_root(path)
    return (
        isinstance(statement, ast.ImportFrom)
        and (
            statement.level > 0
            or (
                statement.module is not None
                and package_root is not None
                and (
                    statement.module == package_root
                    or statement.module.startswith(f"{package_root}.")
                )
            )
        )
    ) or (
        isinstance(statement, ast.Import)
        and package_root is not None
        and any(
            alias.asname is not None
            and (alias.name == package_root or alias.name.startswith(f"{package_root}."))
            for alias in statement.names
        )
    )


def _extract_python_star_reexport_statements(lines: list[str], *, path: str) -> set[str]:
    statements: set[str] = set()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not _is_python_top_level_statement(line):
            index += 1
            continue
        if not PYTHON_IMPORT_START_PATTERN.search(line):
            index += 1
            continue
        statement_source, index = _collect_python_import_statement(lines, index)
        try:
            module = ast.parse(statement_source)
        except SyntaxError:
            continue
        if len(module.body) != 1:
            continue
        statement = module.body[0]
        if not _is_python_public_reexport_statement(statement, path=path):
            continue
        if isinstance(statement, ast.ImportFrom) and any(
            alias.name == "*" for alias in statement.names
        ):
            statements.add(statement_source)
    return statements


def _workspace_python_api_reexport_names(path: str) -> set[str] | None:
    raw_path = Path(path.strip())
    normalized = raw_path.as_posix().lower()
    if not (normalized == "api.py" or normalized.endswith("/api.py")):
        return None

    init_path = raw_path.parent / "__init__.py"
    lines = _read_workspace_python_lines(str(init_path))
    if lines is None:
        return set()

    package_root = _python_package_root(path)
    exports: set[str] = set()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not _is_python_top_level_statement(line):
            index += 1
            continue
        if not PYTHON_IMPORT_START_PATTERN.search(line):
            index += 1
            continue

        statement_source, index = _collect_python_import_statement(lines, index)
        try:
            module = ast.parse(statement_source)
        except SyntaxError:
            continue
        if len(module.body) != 1 or not isinstance(module.body[0], ast.ImportFrom):
            continue

        statement = module.body[0]
        is_api_reexport = (statement.level > 0 and statement.module == "api") or (
            statement.module is not None
            and package_root is not None
            and statement.module == f"{package_root}.api"
        )
        if not is_api_reexport:
            continue
        if any(alias.name == "*" for alias in statement.names):
            return None
        exports.update(
            alias.asname or alias.name
            for alias in statement.names
            if not (alias.asname or alias.name).startswith("_")
        )

    return exports


def _looks_like_python_import_only_facade(lines: list[str]) -> bool:
    index = 0
    while index < len(lines):
        line = lines[index]
        if not _is_python_top_level_statement(line):
            index += 1
            continue
        stripped = line.strip()
        if not stripped:
            index += 1
            continue
        if stripped.startswith(('"', "'")):
            index += 1
            continue
        if PYTHON_TYPE_CHECKING_PATTERN.search(line):
            index += 1
            continue
        if PYTHON_IMPORT_START_PATTERN.search(line):
            _, index = _collect_python_import_statement(lines, index)
            continue
        if PYTHON_ALL_EXPORT_START_PATTERN.search(line):
            _, index = _collect_python_all_assignment(lines, index)
            continue
        assignment_match = PYTHON_PUBLIC_ASSIGNMENT_PATTERN.search(line)
        if assignment_match:
            name = assignment_match.group(1)
            if name.startswith("__") and name.endswith("__"):
                index += 1
                continue
        return False
    return True


def _looks_like_python_reexport_facade(
    lines: list[str],
    *,
    path: str,
    workspace_lines: list[str] | None = None,
) -> bool:
    if _is_python_reexport_surface(path):
        return True
    normalized = path.strip().replace("\\", "/").strip("/").lower()
    if not (normalized == "api.py" or normalized.endswith("/api.py")):
        return False
    api_reexport_names = _workspace_python_api_reexport_names(path)
    if api_reexport_names is None or api_reexport_names:
        return True
    candidate_lines = workspace_lines if workspace_lines is not None else lines
    return _looks_like_python_import_only_facade(candidate_lines)


def _workspace_python_all_contract(path: str) -> _PythonAllContract | None:
    lines = _read_workspace_python_lines(path)
    if lines is None:
        return None
    return _extract_python_all_contract(lines)


def _python_statement_anchor(line: str | None) -> str | None:
    if line is None:
        return None
    stripped = line.strip()
    if not stripped:
        return None
    if "=" in stripped:
        left, right = stripped.split("=", 1)
        if left.strip() and not right.startswith("="):
            return left.strip()
    return stripped


def _infer_python_constructor_class_from_workspace(
    path: str,
    *,
    body_anchor: str | None,
) -> str | None:
    lines = _read_workspace_python_lines(path)
    if lines is None:
        return None

    candidates: list[str] = []
    current_top_level_class: str | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        is_top_level = _is_python_top_level_statement(line)
        class_match = PYTHON_PUBLIC_CLASS_PATTERN.search(line) if is_top_level else None
        if class_match and not line.lstrip().startswith("@"):
            class_name = class_match.group(1)
            current_top_level_class = class_name if not class_name.startswith("_") else None
            index += 1
            continue
        if is_top_level and not class_match and line.strip():
            current_top_level_class = None

        def_start = PYTHON_DEF_START_PATTERN.search(line)
        if not def_start:
            index += 1
            continue

        signature_source, next_index = _collect_python_signature_source(lines, index)
        def_match = PYTHON_PUBLIC_DEF_PATTERN.search(signature_source)
        if (
            current_top_level_class
            and def_match
            and def_match.group(1) == "__init__"
            and _python_indent_level(line) > 0
        ):
            next_body_line: str | None = None
            if next_index < len(lines):
                candidate = lines[next_index].strip()
                if candidate:
                    next_body_line = candidate
            if body_anchor is None or _python_statement_anchor(
                next_body_line
            ) == _python_statement_anchor(body_anchor):
                candidates.append(current_top_level_class)
        index = next_index

    unique_candidates = sorted(set(candidates))
    if len(unique_candidates) == 1:
        return unique_candidates[0]
    return None


def _has_ambiguous_python_constructor_match(
    path: str,
    *,
    body_anchor: str | None,
) -> bool:
    lines = _read_workspace_python_lines(path)
    if lines is None:
        return False

    candidates: list[str] = []
    current_top_level_class: str | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        is_top_level = _is_python_top_level_statement(line)
        class_match = PYTHON_PUBLIC_CLASS_PATTERN.search(line) if is_top_level else None
        if class_match and not line.lstrip().startswith("@"):
            class_name = class_match.group(1)
            current_top_level_class = class_name if not class_name.startswith("_") else None
            index += 1
            continue
        if is_top_level and not class_match and line.strip():
            current_top_level_class = None

        def_start = PYTHON_DEF_START_PATTERN.search(line)
        if not def_start:
            index += 1
            continue

        signature_source, next_index = _collect_python_signature_source(lines, index)
        def_match = PYTHON_PUBLIC_DEF_PATTERN.search(signature_source)
        if (
            current_top_level_class
            and def_match
            and def_match.group(1) == "__init__"
            and _python_indent_level(line) > 0
        ):
            next_body_line: str | None = None
            if next_index < len(lines):
                candidate = lines[next_index].strip()
                if candidate:
                    next_body_line = candidate
            if body_anchor is None or _python_statement_anchor(
                next_body_line
            ) == _python_statement_anchor(body_anchor):
                candidates.append(current_top_level_class)
        index = next_index

    return len(set(candidates)) > 1


def _classify_nested_python_constructor_context(
    path: str,
    *,
    body_anchor: str | None,
) -> str:
    lines = _read_workspace_python_lines(path)
    if lines is None:
        return "unknown"

    stack: list[tuple[str, int, str | None]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        indent = _python_indent_level(line)
        if line.strip():
            while stack and indent <= stack[-1][1]:
                stack.pop()

        class_match = PYTHON_PUBLIC_CLASS_PATTERN.search(line)
        if class_match and not line.lstrip().startswith("@"):
            class_name = class_match.group(1)
            stack.append(("class", indent, class_name if not class_name.startswith("_") else None))
            index += 1
            continue

        def_start = PYTHON_DEF_START_PATTERN.search(line)
        if not def_start:
            index += 1
            continue

        signature_source, next_index = _collect_python_signature_source(lines, index)
        def_match = PYTHON_PUBLIC_DEF_PATTERN.search(signature_source)
        if def_match and def_match.group(1) == "__init__":
            next_body_line: str | None = None
            if next_index < len(lines):
                candidate = lines[next_index].strip()
                if candidate:
                    next_body_line = candidate
            if body_anchor is None or _python_statement_anchor(
                next_body_line
            ) == _python_statement_anchor(body_anchor):
                public_class_depth = len(
                    [entry for entry in stack if entry[0] == "class" and entry[2] is not None]
                )
                has_function_scope = any(entry[0] == "def" for entry in stack)
                if has_function_scope:
                    return "nonpublic"
                if public_class_depth > 1:
                    return "public"
                return "unknown"

        if def_match:
            stack.append(("def", indent, None))
            index = next_index
            continue

        index += 1

    return "unknown"


def _classify_nested_python_constructor_context_from_hunk(
    file_diff: _FileDiff,
    *,
    change_index: int,
) -> str:
    current_indent = _python_indent_level(file_diff.ordered_lines[change_index][1])
    if current_indent <= 4:
        return "unknown"

    public_class_depth = 0
    has_function_scope = False
    scope_indent = current_indent
    cursor = change_index - 1
    while cursor >= 0:
        candidate = file_diff.ordered_lines[cursor][1]
        if not candidate.strip():
            cursor -= 1
            continue

        candidate_indent = _python_indent_level(candidate)
        if candidate_indent >= scope_indent:
            cursor -= 1
            continue

        class_match = PYTHON_PUBLIC_CLASS_PATTERN.search(candidate)
        if class_match and not candidate.lstrip().startswith("@"):
            class_name = class_match.group(1)
            if not class_name.startswith("_"):
                public_class_depth += 1
            scope_indent = candidate_indent
            cursor -= 1
            continue

        if PYTHON_DEF_START_PATTERN.search(candidate):
            has_function_scope = True
            scope_indent = candidate_indent
            cursor -= 1
            continue

        cursor -= 1

    if has_function_scope:
        return "nonpublic"
    if public_class_depth > 1:
        return "public"
    return "unknown"


def _extract_python_all_contract(lines: list[str]) -> _PythonAllContract:
    exports: set[str] = set()
    has_explicit_all = False
    has_unsupported_all = False
    index = 0
    while index < len(lines):
        line = lines[index]
        if not _is_python_top_level_statement(line):
            index += 1
            continue
        match = PYTHON_ALL_EXPORT_START_PATTERN.search(line)
        if not match:
            index += 1
            continue
        has_explicit_all = True
        assignment_source, index = _collect_python_all_assignment(lines, index)
        operator = match.group(1)
        try:
            module = ast.parse(assignment_source)
        except SyntaxError:
            has_unsupported_all = True
            continue
        if len(module.body) != 1:
            has_unsupported_all = True
            continue
        statement = module.body[0]
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            supported, values = _extract_python_string_names(statement.value)
            if not supported:
                has_unsupported_all = True
                continue
            exports = {member for member in values if not member.startswith("_")}
        elif isinstance(statement, ast.AugAssign) and isinstance(statement.op, ast.Add):
            supported, values = _extract_python_string_names(statement.value)
            if not supported:
                has_unsupported_all = True
                continue
            if operator == "=":
                exports = {member for member in values if not member.startswith("_")}
            else:
                exports.update(member for member in values if not member.startswith("_"))
        else:
            has_unsupported_all = True
    if has_unsupported_all:
        return _PythonAllContract(
            has_explicit=has_explicit_all,
            is_supported=False,
            exports=set(),
        )
    return _PythonAllContract(
        has_explicit=has_explicit_all,
        is_supported=True,
        exports=exports,
    )


def _extract_python_implicit_public_names(
    lines: list[str],
    *,
    path: str,
    workspace_lines: list[str] | None = None,
    explicit_public_names: set[str] | None = None,
) -> set[str]:
    exports: set[str] = set()
    allow_reexport_imports = _looks_like_python_reexport_facade(
        lines,
        path=path,
        workspace_lines=workspace_lines,
    )

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

        if allow_reexport_imports and PYTHON_IMPORT_START_PATTERN.search(line):
            statement_source, index = _collect_python_import_statement(lines, index)
            explicit_alias_names = _extract_python_explicit_import_alias_names(
                statement_source,
                path=path,
            )
            exports.update(
                name
                for name in _extract_python_imported_names(statement_source, path=path)
                if (
                    explicit_public_names is None
                    or name in explicit_public_names
                    or name in explicit_alias_names
                )
            )
            continue

        assignment_match = PYTHON_PUBLIC_ASSIGNMENT_PATTERN.search(line)
        if assignment_match:
            name = assignment_match.group(1)
            if not name.startswith("_") and name != "__all__":
                exports.add(name)
        index += 1

    return exports


def _extract_python_local_public_names(lines: list[str], *, path: str) -> set[str]:
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


def _extract_python_public_names(
    lines: list[str],
    *,
    path: str,
    workspace_lines: list[str] | None = None,
    explicit_public_names: set[str] | None = None,
) -> set[str]:
    all_contract = _extract_python_all_contract(lines)
    if all_contract.has_explicit and all_contract.is_supported:
        return all_contract.exports
    return _extract_python_implicit_public_names(
        lines,
        path=path,
        workspace_lines=workspace_lines,
        explicit_public_names=explicit_public_names,
    )


def _extract_python_import_public_names(lines: list[str], *, path: str) -> set[str]:
    exports: set[str] = set()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not _is_python_top_level_statement(line):
            index += 1
            continue
        if not PYTHON_IMPORT_START_PATTERN.search(line):
            index += 1
            continue
        statement_source, index = _collect_python_import_statement(lines, index)
        exports.update(_extract_python_imported_names(statement_source, path=path))
    return exports


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
        stripped = collected[-1].strip()
        if paren_depth <= 0 and (
            stripped.endswith(":")
            or re.search(r"^\s*(?:async\s+)?def\b.*:\s*(?:\.\.\.|pass\b.*|return\b.*)$", stripped)
        ):
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

        if is_top_level and not class_match and line.strip():
            current_top_level_class = None

        def_start = PYTHON_DEF_START_PATTERN.search(line)
        if not def_start:
            index += 1
            continue
        signature_source, _block_is_target, index = _collect_python_signature_block(
            version_lines,
            index,
        )
        def_match = PYTHON_PUBLIC_DEF_PATTERN.search(signature_source)
        if not def_match:
            continue

        name = def_match.group(1)
        params = re.sub(r"\s+", "", def_match.group(2))
        return_type = _normalize_type(def_match.group(3))
        param_list = _split_top_level_params(def_match.group(2))
        next_body_line: str | None = None
        if index < len(version_lines):
            candidate = version_lines[index][0]
            if _python_indent_level(candidate) > _python_indent_level(line) and candidate.strip():
                next_body_line = candidate.strip()
        if (
            name == "__init__"
            and param_list
            and param_list[0].strip() == "self"
            and _python_indent_level(line) > 0
        ):
            if _python_indent_level(line) > 4:
                continue
            inferred_class = (
                current_top_level_class
                or _infer_python_constructor_class_from_workspace(
                    file_diff.path,
                    body_anchor=next_body_line,
                )
            )
            if inferred_class:
                symbol_name = f"{inferred_class}.__init__"
            else:
                continue
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


def _normalize_python_annotation(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    return ast.unparse(node).strip()


def _parse_python_parameter_specs(params: str) -> list[_PythonParameterSpec] | None:
    try:
        module = ast.parse(f"def _bumpkin_probe({params}):\n    pass\n")
    except SyntaxError:
        return None
    if len(module.body) != 1 or not isinstance(module.body[0], ast.FunctionDef):
        return None

    arguments = module.body[0].args
    specs: list[_PythonParameterSpec] = []
    positional_args = [*arguments.posonlyargs, *arguments.args]
    positional_defaults: list[ast.expr | None] = [None] * (
        len(positional_args) - len(arguments.defaults)
    ) + list(arguments.defaults)

    for index, argument in enumerate(arguments.posonlyargs):
        specs.append(
            _PythonParameterSpec(
                name=argument.arg,
                kind="posonly",
                required=positional_defaults[index] is None,
                annotation=_normalize_python_annotation(argument.annotation),
            )
        )

    positional_offset = len(arguments.posonlyargs)
    for offset, argument in enumerate(arguments.args):
        specs.append(
            _PythonParameterSpec(
                name=argument.arg,
                kind="arg",
                required=positional_defaults[positional_offset + offset] is None,
                annotation=_normalize_python_annotation(argument.annotation),
            )
        )

    if arguments.vararg is not None:
        specs.append(
            _PythonParameterSpec(
                name=arguments.vararg.arg,
                kind="vararg",
                required=False,
                annotation=_normalize_python_annotation(arguments.vararg.annotation),
            )
        )

    for argument, default in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=False):
        specs.append(
            _PythonParameterSpec(
                name=argument.arg,
                kind="kwonly",
                required=default is None,
                annotation=_normalize_python_annotation(argument.annotation),
            )
        )

    if arguments.kwarg is not None:
        specs.append(
            _PythonParameterSpec(
                name=arguments.kwarg.arg,
                kind="varkw",
                required=False,
                annotation=_normalize_python_annotation(arguments.kwarg.annotation),
            )
        )

    return specs


def _same_python_parameter_surface(
    old_param: _PythonParameterSpec,
    new_param: _PythonParameterSpec,
) -> bool:
    return (
        _is_python_parameter_name_compatible(old_param, new_param)
        and old_param.kind == new_param.kind
        and old_param.required == new_param.required
        and old_param.annotation == new_param.annotation
    )


def _is_python_parameter_name_compatible(
    old_param: _PythonParameterSpec,
    new_param: _PythonParameterSpec,
) -> bool:
    if old_param.kind in {"posonly", "vararg", "varkw"}:
        return True
    return old_param.name == new_param.name


def _is_python_parameter_kind_compatible(
    old_param: _PythonParameterSpec,
    new_param: _PythonParameterSpec,
) -> bool:
    if old_param.kind == new_param.kind:
        return True
    return new_param.kind == "arg" and old_param.kind in {"kwonly", "posonly"}


def _is_python_parameter_surface_compatible(
    old_param: _PythonParameterSpec,
    new_param: _PythonParameterSpec,
) -> bool:
    return (
        _is_python_parameter_name_compatible(old_param, new_param)
        and _is_python_parameter_kind_compatible(old_param, new_param)
        and old_param.required == new_param.required
        and old_param.annotation == new_param.annotation
    )


def _has_compatible_python_parameter_surface(old_params: str, new_params: str) -> bool:
    old_specs = _parse_python_parameter_specs(old_params)
    new_specs = _parse_python_parameter_specs(new_params)
    if old_specs is None or new_specs is None or len(old_specs) != len(new_specs):
        return False
    return all(
        _is_python_parameter_surface_compatible(old_spec, new_spec)
        for old_spec, new_spec in zip(old_specs, new_specs, strict=False)
    )


def _is_optional_widening(old_params: str, new_params: str) -> bool:
    old_specs = _parse_python_parameter_specs(old_params)
    new_specs = _parse_python_parameter_specs(new_params)
    if old_specs is not None and new_specs is not None:
        if len(new_specs) < len(old_specs):
            return False
        if not all(
            _same_python_parameter_surface(old_spec, new_spec)
            for old_spec, new_spec in zip(old_specs, new_specs[: len(old_specs)], strict=False)
        ):
            return False
        extras = new_specs[len(old_specs) :]
        return bool(extras) and all(not extra.required for extra in extras)

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
    old_specs = _parse_python_parameter_specs(old_params)
    new_specs = _parse_python_parameter_specs(new_params)
    if old_specs is not None and new_specs is not None:
        if len(new_specs) < len(old_specs):
            return True

        for index, old_spec in enumerate(old_specs):
            if index >= len(new_specs):
                return True
            new_spec = new_specs[index]
            if not _is_python_parameter_name_compatible(
                old_spec, new_spec
            ) or not _is_python_parameter_kind_compatible(old_spec, new_spec):
                return False
            if not old_spec.required and new_spec.required:
                return True

        extras = new_specs[len(old_specs) :]
        return any(extra.required for extra in extras)

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
            and added_floor is not None
            and (removed_floor is None or added_floor > removed_floor)
        ):
            counter += 1
            findings.append(
                _build_finding(
                    severity="MAJOR",
                    rule="python_requires_floor_raised",
                    confidence="high",
                    title=(
                        f"Declared supported Python floor: {'.'.join(map(str, added_floor))}"
                        if removed_floor is None
                        else (
                            "Raised supported Python floor: "
                            f"{'.'.join(map(str, removed_floor))} -> {'.'.join(map(str, added_floor))}"
                        )
                    ),
                    why=(
                        "Declaring or raising the minimum supported Python version is a "
                        "breaking compatibility change for downstream users on older runtimes."
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
        workspace_lines = _read_workspace_python_lines(file_diff.path)
        workspace_api_reexport_names = _workspace_python_api_reexport_names(file_diff.path)
        removed_import_public_names = _extract_python_import_public_names(
            removed_version_lines,
            path=file_diff.path,
        )
        added_import_public_names = _extract_python_import_public_names(
            added_version_lines,
            path=file_diff.path,
        )
        removed_local_public_names = _extract_python_local_public_names(
            removed_version_lines,
            path=file_diff.path,
        )
        added_local_public_names = _extract_python_local_public_names(
            added_version_lines,
            path=file_diff.path,
        )
        removed_star_reexports = _extract_python_star_reexport_statements(
            removed_version_lines,
            path=file_diff.path,
        )
        added_star_reexports = _extract_python_star_reexport_statements(
            added_version_lines,
            path=file_diff.path,
        )
        api_explicit_public_names: set[str] | None = None
        if workspace_api_reexport_names:
            api_explicit_public_names = set(workspace_api_reexport_names)
            if workspace_api_reexport_names & (
                removed_import_public_names | added_import_public_names
            ):
                api_explicit_public_names.update(
                    removed_import_public_names | added_import_public_names
                )
        removed_all_contract = _extract_python_all_contract(removed_version_lines)
        added_all_contract = _extract_python_all_contract(added_version_lines)
        removed_has_explicit_all = (
            removed_all_contract.has_explicit and removed_all_contract.is_supported
        )
        added_has_explicit_all = added_all_contract.has_explicit and added_all_contract.is_supported
        removed_all_exports = set(removed_all_contract.exports)
        added_all_exports = set(added_all_contract.exports)
        workspace_all_contract = _workspace_python_all_contract(file_diff.path)
        unresolved_all_contract = any(
            contract is not None and contract.has_explicit and not contract.is_supported
            for contract in (
                removed_all_contract,
                added_all_contract,
                workspace_all_contract,
            )
        )
        if unresolved_all_contract:
            touched_all_assignment = any(
                "__all__" in line for line in (*file_diff.added_lines, *file_diff.removed_lines)
            )
            candidate_names = sorted(
                _extract_python_implicit_public_names(
                    removed_version_lines,
                    path=file_diff.path,
                    workspace_lines=workspace_lines,
                    explicit_public_names=api_explicit_public_names,
                )
                | _extract_python_implicit_public_names(
                    added_version_lines,
                    path=file_diff.path,
                    workspace_lines=workspace_lines,
                    explicit_public_names=api_explicit_public_names,
                )
            )
            if candidate_names or touched_all_assignment:
                counter += 1
                findings.append(
                    _build_finding(
                        severity="MANUAL_REVIEW",
                        rule="python_all_unresolved",
                        confidence="low",
                        title="Unable to resolve explicit Python __all__ contract",
                        why=(
                            "This module declares __all__ using a dynamic or unsupported "
                            "expression, so Bumpkin cannot deterministically confirm whether the "
                            "changed symbol is part of the public surface."
                        ),
                        path=file_diff.path,
                        snippet=next(
                            (
                                line
                                for line in (*file_diff.added_lines, *file_diff.removed_lines)
                                if "__all__" in line
                            ),
                            file_diff.added_lines[0]
                            if file_diff.added_lines
                            else (file_diff.removed_lines[0] if file_diff.removed_lines else ""),
                        ),
                        counter=counter,
                    )
                )
            continue
        if removed_star_reexports != added_star_reexports and (
            removed_star_reexports or added_star_reexports
        ):
            counter += 1
            findings.append(
                _build_finding(
                    severity="MANUAL_REVIEW",
                    rule="python_star_reexport_changed",
                    confidence="low",
                    title="Changed Python star re-export requires manual review",
                    why=(
                        "A Python facade changed a star re-export, so Bumpkin cannot "
                        "deterministically enumerate which public symbols were added or removed."
                    ),
                    path=file_diff.path,
                    snippet=next(
                        (
                            line
                            for line in (*file_diff.added_lines, *file_diff.removed_lines)
                            if "import *" in line
                        ),
                        file_diff.added_lines[0]
                        if file_diff.added_lines
                        else (file_diff.removed_lines[0] if file_diff.removed_lines else ""),
                    ),
                    counter=counter,
                )
            )
            continue
        workspace_explicit_exports = (
            set(workspace_all_contract.exports)
            if workspace_all_contract is not None
            and workspace_all_contract.has_explicit
            and workspace_all_contract.is_supported
            else None
        )
        removed_exports = (
            removed_all_exports
            if removed_has_explicit_all
            else _extract_python_public_names(
                removed_version_lines,
                path=file_diff.path,
                workspace_lines=workspace_lines,
                explicit_public_names=api_explicit_public_names,
            )
        )
        added_exports = (
            added_all_exports
            if added_has_explicit_all
            else _extract_python_public_names(
                added_version_lines,
                path=file_diff.path,
                workspace_lines=workspace_lines,
                explicit_public_names=api_explicit_public_names,
            )
        )
        if workspace_explicit_exports is not None:
            if not removed_has_explicit_all:
                removed_exports = removed_exports & workspace_explicit_exports
            if not added_has_explicit_all:
                added_exports = added_exports & workspace_explicit_exports
        workspace_public_names = (
            _extract_python_public_names(
                workspace_lines,
                path=file_diff.path,
                workspace_lines=workspace_lines,
                explicit_public_names=api_explicit_public_names,
            )
            if workspace_lines is not None
            else None
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
        if workspace_explicit_exports is not None:
            if not removed_has_explicit_all:
                removed_classes = removed_classes & workspace_explicit_exports
            if not added_has_explicit_all:
                added_classes = added_classes & workspace_explicit_exports
        ambiguous_constructor_change = any(
            PYTHON_DEF_START_PATTERN.search(line)
            and "__init__" in line
            and _python_indent_level(line) > 0
            for line in (*file_diff.added_lines, *file_diff.removed_lines)
        ) and _has_ambiguous_python_constructor_match(file_diff.path, body_anchor=None)
        nested_constructor_change = False
        for index, (prefix, line) in enumerate(file_diff.ordered_lines):
            if prefix not in {"+", "-"}:
                continue
            if not (PYTHON_DEF_START_PATTERN.search(line) and "__init__" in line):
                continue
            if _python_indent_level(line) <= 4:
                continue

            context = _classify_nested_python_constructor_context_from_hunk(
                file_diff,
                change_index=index,
            )
            if context == "unknown":
                next_body_line: str | None = None
                cursor = index + 1
                while cursor < len(file_diff.ordered_lines):
                    _next_prefix, candidate = file_diff.ordered_lines[cursor]
                    if candidate.strip() and _python_indent_level(candidate) > _python_indent_level(
                        line
                    ):
                        next_body_line = candidate.strip()
                        break
                    if candidate.strip() and _python_indent_level(
                        candidate
                    ) <= _python_indent_level(line):
                        break
                    cursor += 1
                context = _classify_nested_python_constructor_context(
                    file_diff.path,
                    body_anchor=next_body_line,
                )

            if context == "public":
                nested_constructor_change = True
                break

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
        unreexported_local_public_exports: set[str] = set()
        if workspace_api_reexport_names:
            shared_local_public_exports = removed_local_public_names & added_local_public_names
            unreexported_local_public_exports = (
                shared_local_public_exports - workspace_api_reexport_names
            )
            shared_public_exports = (
                shared_public_exports - removed_local_public_names - added_local_public_names
            ) | (shared_local_public_exports & workspace_api_reexport_names)
        workspace_public_classes = workspace_public_names or set()
        shared_symbols = sorted(
            symbol
            for symbol in (set(removed_signatures) & set(added_signatures))
            if symbol in shared_public_exports
            or (
                symbol.endswith(".__init__")
                and (
                    symbol.rsplit(".", 1)[0] in shared_public_exports
                    or symbol.rsplit(".", 1)[0] in workspace_public_classes
                )
            )
        )
        for symbol in shared_symbols:
            old_sigs = removed_signatures.get(symbol, [])
            new_sigs = added_signatures.get(symbol, [])
            if not old_sigs or not new_sigs:
                continue

            old_signature_keys = {_signature_key(signature) for signature in old_sigs}
            new_signature_keys = {_signature_key(signature) for signature in new_sigs}
            if len(old_sigs) > 1 or len(new_sigs) > 1:
                if old_signature_keys == new_signature_keys:
                    continue
                removed_overloads = old_signature_keys - new_signature_keys
                added_overloads = new_signature_keys - old_signature_keys
                counter += 1
                if removed_overloads and not added_overloads:
                    findings.append(
                        _build_finding(
                            severity="MAJOR",
                            rule="export_overload_removed",
                            confidence="high",
                            title=f"Removed public Python overload(s): {symbol}",
                            why=(
                                "Removing a public overload narrows the supported call surface "
                                "for downstream users."
                            ),
                            path=file_diff.path,
                            snippet=old_sigs[0].source,
                            counter=counter,
                        )
                    )
                elif added_overloads and not removed_overloads:
                    findings.append(
                        _build_finding(
                            severity="MINOR",
                            rule="export_overload_added",
                            confidence="medium",
                            title=f"Added public Python overload(s): {symbol}",
                            why=(
                                "Adding a public overload expands the supported call surface "
                                "without removing existing ones."
                            ),
                            path=file_diff.path,
                            snippet=new_sigs[0].source,
                            counter=counter,
                        )
                    )
                else:
                    findings.append(
                        _build_finding(
                            severity="MAJOR",
                            rule="export_overload_changed",
                            confidence="high",
                            title=f"Changed public Python overload set: {symbol}",
                            why=(
                                "Changing the supported overload set can remove previously valid "
                                "call patterns for downstream users."
                            ),
                            path=file_diff.path,
                            snippet=new_sigs[0].source,
                            counter=counter,
                        )
                    )
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

            if _has_compatible_python_parameter_surface(old_params, new_params):
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

        if unreexported_local_public_exports:
            unresolved_local_symbols = sorted(
                symbol
                for symbol in (set(removed_signatures) & set(added_signatures))
                if (
                    symbol in unreexported_local_public_exports
                    or (
                        symbol.endswith(".__init__")
                        and symbol.rsplit(".", 1)[0] in unreexported_local_public_exports
                    )
                )
                and set(map(_signature_key, removed_signatures.get(symbol, [])))
                != set(map(_signature_key, added_signatures.get(symbol, [])))
            )
            if unresolved_local_symbols:
                counter += 1
                findings.append(
                    _build_finding(
                        severity="MANUAL_REVIEW",
                        rule="python_api_module_local_surface_changed",
                        confidence="low",
                        title=(
                            "Changed local api.py public-surface candidate requires manual review: "
                            f"{', '.join(unresolved_local_symbols[:3])}"
                        ),
                        why=(
                            "This api.py module changed a local top-level symbol that is not "
                            "re-exported from the package root. Bumpkin cannot deterministically "
                            "tell whether it is part of the public submodule API or an internal "
                            "helper, so the change should be reviewed manually."
                        ),
                        path=file_diff.path,
                        snippet=next(
                            (
                                line
                                for line in (*file_diff.added_lines, *file_diff.removed_lines)
                                if any(
                                    symbol.rsplit(".", 1)[-1] in line
                                    for symbol in unresolved_local_symbols
                                )
                            ),
                            file_diff.added_lines[0]
                            if file_diff.added_lines
                            else (file_diff.removed_lines[0] if file_diff.removed_lines else ""),
                        ),
                        counter=counter,
                    )
                )

        if nested_constructor_change:
            counter += 1
            findings.append(
                _build_finding(
                    severity="MANUAL_REVIEW",
                    rule="python_nested_constructor_changed",
                    confidence="low",
                    title="Changed nested Python constructor requires manual review",
                    why=(
                        "A nested Python class constructor changed, and Bumpkin does not "
                        "deterministically classify nested-class API compatibility yet."
                    ),
                    path=file_diff.path,
                    snippet=next(
                        (
                            line
                            for line in (*file_diff.added_lines, *file_diff.removed_lines)
                            if "__init__" in line
                        ),
                        file_diff.added_lines[0]
                        if file_diff.added_lines
                        else (file_diff.removed_lines[0] if file_diff.removed_lines else ""),
                    ),
                    counter=counter,
                )
            )

        if ambiguous_constructor_change:
            counter += 1
            findings.append(
                _build_finding(
                    severity="MANUAL_REVIEW",
                    rule="python_constructor_ambiguous",
                    confidence="low",
                    title="Changed Python constructor requires manual review",
                    why=(
                        "A public __init__ changed, but Bumpkin could not uniquely match it to a "
                        "single class from the workspace context."
                    ),
                    path=file_diff.path,
                    snippet=next(
                        (
                            line
                            for line in (*file_diff.added_lines, *file_diff.removed_lines)
                            if "__init__" in line
                        ),
                        file_diff.added_lines[0]
                        if file_diff.added_lines
                        else (file_diff.removed_lines[0] if file_diff.removed_lines else ""),
                    ),
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
    return _reindex_findings(findings)
