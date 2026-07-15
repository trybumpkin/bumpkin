from __future__ import annotations

import re

from bumpkin.analysis.finding_diff import FileDiff
from bumpkin.analysis.finding_python_surface import (
    PYTHON_DEF_START_PATTERN,
    PYTHON_PUBLIC_CLASS_PATTERN,
    PYTHON_PUBLIC_DEF_PATTERN,
)
from bumpkin.analysis.finding_python_surface_base import (
    WorkspaceLoader,
    collect_python_signature_source,
    python_indent_level,
    strip_python_inline_comment,
)
from bumpkin.analysis.python_signature_context import (
    PythonFunctionSignature,
    infer_python_constructor_class_from_workspace,
    infer_python_member_class_from_workspace,
    python_class_scope_is_public,
    python_public_class_path,
)


def iter_python_version_lines(
    file_diff: FileDiff,
    *,
    target_prefix: str,
) -> list[tuple[str, bool]]:
    return [
        (line, prefix == target_prefix)
        for prefix, line in file_diff.ordered_lines
        if prefix in {" ", target_prefix}
    ]


def collect_python_signature_block(
    version_lines: list[tuple[str, bool]],
    start_index: int,
) -> tuple[str, bool, int]:
    collected = [version_lines[start_index][0]]
    block_is_target = version_lines[start_index][1]
    paren_depth = collected[0].count("(") - collected[0].count(")")
    cursor = start_index + 1
    while cursor < len(version_lines):
        stripped = strip_python_inline_comment(collected[-1]).strip()
        if paren_depth <= 0 and (
            stripped.endswith(":")
            or re.search(
                r"^\s*(?:async\s+)?def\b.*:\s*(?:\.\.\.|pass\b.*|return\b.*)$",
                stripped,
            )
        ):
            break
        line, is_target_line = version_lines[cursor]
        collected.append(line)
        block_is_target = block_is_target or is_target_line
        paren_depth += line.count("(") - line.count(")")
        cursor += 1
    return " ".join(line.strip() for line in collected), block_is_target, cursor


def collect_python_decorator_names(
    version_lines: list[tuple[str, bool]],
    def_index: int,
) -> set[str]:
    decorators: set[str] = set()
    def_line = version_lines[def_index][0]
    def_indent = python_indent_level(def_line)
    cursor = def_index - 1
    while cursor >= 0:
        line = version_lines[cursor][0]
        stripped = line.strip()
        if not stripped or python_indent_level(line) != def_indent or not stripped.startswith("@"):
            break
        decorator_name = stripped[1:].split("(", 1)[0].strip()
        if decorator_name:
            decorators.add(decorator_name.split(".")[-1])
        cursor -= 1
    return decorators


def python_method_kind_from_decorators(decorators: set[str]) -> str:
    for name, kind in (
        ("staticmethod", "staticmethod"),
        ("classmethod", "classmethod"),
        ("setter", "property-setter"),
        ("deleter", "property-deleter"),
        ("getter", "property-getter"),
    ):
        if name in decorators:
            return kind
    return (
        "property"
        if any(name == "property" or name.endswith("property") for name in decorators)
        else "instance"
    )


def is_public_python_member_name(name: str) -> bool:
    return (
        name == "__init__"
        or (name.startswith("__") and name.endswith("__"))
        or not name.startswith("_")
    )


def _normalize_type(raw_type: str | None) -> str | None:
    if raw_type is None:
        return None
    cleaned = re.sub(r"\s+", " ", raw_type).strip()
    return cleaned or None


def extract_python_signatures(
    file_diff: FileDiff,
    *,
    target_prefix: str,
    workspace_loader: WorkspaceLoader | None = None,
) -> dict[str, list[PythonFunctionSignature]]:
    signatures: dict[str, list[PythonFunctionSignature]] = {}
    scope_stack: list[tuple[str, int, str | None]] = []
    version_lines = iter_python_version_lines(file_diff, target_prefix=target_prefix)
    index = 0
    while index < len(version_lines):
        line, _is_target_line = version_lines[index]
        indent = python_indent_level(line)
        if line.strip():
            while scope_stack and indent <= scope_stack[-1][1]:
                scope_stack.pop()
        class_match = PYTHON_PUBLIC_CLASS_PATTERN.search(line)
        if class_match and not line.lstrip().startswith("@"):
            name = class_match.group(1)
            scope_stack.append(("class", indent, name if not name.startswith("_") else None))
            index += 1
            continue
        if not PYTHON_DEF_START_PATTERN.search(line):
            index += 1
            continue
        signature_start = index
        signature_source, _block_is_target, index = collect_python_signature_block(
            version_lines, index
        )
        def_match = PYTHON_PUBLIC_DEF_PATTERN.search(signature_source)
        if not def_match:
            continue
        symbol_name, method_kind = _resolve_signature_symbol(
            file_diff=file_diff,
            line=line,
            index=index,
            def_match=def_match,
            scope_stack=scope_stack,
            decorators=collect_python_decorator_names(version_lines, signature_start),
            version_lines=version_lines,
            workspace_loader=workspace_loader,
        )
        if symbol_name is None:
            continue
        signatures.setdefault(symbol_name, []).append(
            PythonFunctionSignature(
                name=symbol_name,
                params=re.sub(r"\s+", "", def_match.group(2)),
                return_type=_normalize_type(def_match.group(3)),
                is_async=signature_source.lstrip().startswith("async def "),
                source=signature_source,
                method_kind=method_kind,
            )
        )
        scope_stack.append(("def", indent, None))
    return signatures


def _resolve_signature_symbol(
    *,
    file_diff: FileDiff,
    line: str,
    index: int,
    def_match: re.Match[str],
    scope_stack: list[tuple[str, int, str | None]],
    decorators: set[str],
    version_lines: list[tuple[str, bool]],
    workspace_loader: WorkspaceLoader | None,
) -> tuple[str | None, str | None]:
    name = def_match.group(1)
    indent = python_indent_level(line)
    if indent > 0 and not python_class_scope_is_public(scope_stack):
        return None, None
    if indent == 0:
        return (name, None) if indent == 0 else (None, None)
    if not is_public_python_member_name(name) or (name == "__init__" and indent > 4):
        return None, None
    public_class_path = python_public_class_path(scope_stack)
    has_function_scope = any(entry[0] == "def" for entry in scope_stack)
    if public_class_path and not has_function_scope:
        symbol_name = ".".join([*public_class_path, name])
    else:
        next_body_line = _next_body_line(index, version_lines)
        if name == "__init__":
            inferred = infer_python_constructor_class_from_workspace(
                file_diff.path,
                body_anchor=next_body_line,
                workspace_loader=workspace_loader,
            )
        else:
            inferred = infer_python_member_class_from_workspace(
                file_diff.path,
                member_name=name,
                body_anchor=next_body_line,
                workspace_loader=workspace_loader,
            )
        if not inferred:
            return None, None
        symbol_name = f"{inferred}.{name}"
    return symbol_name, python_method_kind_from_decorators(decorators)


def _next_body_line(index: int, version_lines: list[tuple[str, bool]]) -> str | None:
    if index < len(version_lines):
        candidate = version_lines[index][0]
        if candidate.strip():
            return candidate.strip()
    return None


def extract_python_classes(
    lines: list[str],
    *,
    has_explicit_all: bool = False,
    explicit_exports: set[str] | None = None,
    allow_implicit_classes: bool = True,
) -> set[str]:
    if not has_explicit_all and not allow_implicit_classes:
        return set()
    classes: set[str] = set()
    scope_stack: list[tuple[str, int, str | None]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        indent = python_indent_level(line)
        if line.strip():
            while scope_stack and indent <= scope_stack[-1][1]:
                scope_stack.pop()
        match = PYTHON_PUBLIC_CLASS_PATTERN.search(line)
        if not match:
            if not PYTHON_DEF_START_PATTERN.search(line):
                index += 1
                continue
            signature_source, index = collect_python_signature_source(lines, index)
            if PYTHON_PUBLIC_DEF_PATTERN.search(signature_source):
                scope_stack.append(("def", indent, None))
            continue
        name = match.group(1)
        public_name = (
            name
            if not name.startswith("_")
            or (has_explicit_all and explicit_exports and name in explicit_exports)
            else None
        )
        public_class_path = python_public_class_path(scope_stack)
        has_function_scope = any(entry[0] == "def" for entry in scope_stack)
        if indent == 0:
            if has_explicit_all and explicit_exports is not None and name not in explicit_exports:
                scope_stack.append(("class", indent, public_name))
                index += 1
                continue
            if public_name is not None:
                classes.add(name)
        elif public_name is not None and public_class_path and not has_function_scope:
            classes.add(".".join([*public_class_path, name]))
        scope_stack.append(("class", indent, public_name))
        index += 1
    return classes
