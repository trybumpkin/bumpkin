from __future__ import annotations

from dataclasses import dataclass

from bumpkin.analysis.finding_diff import FileDiff
from bumpkin.analysis.finding_python_surface import (
    PYTHON_DEF_START_PATTERN,
    PYTHON_PUBLIC_CLASS_PATTERN,
    PYTHON_PUBLIC_DEF_PATTERN,
)
from bumpkin.analysis.finding_python_surface_base import (
    WorkspaceLoader,
    collect_python_signature_source,
    is_python_top_level_statement,
    python_indent_level,
    read_workspace_python_lines,
)


@dataclass(frozen=True)
class PythonFunctionSignature:
    name: str
    params: str
    return_type: str | None
    is_async: bool
    source: str
    method_kind: str | None = None


def signatures_equivalent(left: PythonFunctionSignature, right: PythonFunctionSignature) -> bool:
    return (
        left.params == right.params
        and left.return_type == right.return_type
        and left.is_async == right.is_async
        and left.method_kind == right.method_kind
    )


def signature_key(signature: PythonFunctionSignature) -> tuple[str, str | None, str, str | None]:
    return (
        signature.params,
        signature.return_type,
        "async" if signature.is_async else "sync",
        signature.method_kind,
    )


def python_symbol_roots(symbol: str) -> tuple[str, str]:
    if "." not in symbol:
        return symbol, symbol
    return symbol.split(".", 1)[0], symbol.rsplit(".", 1)[0]


def python_class_scope_is_public(scope_stack: list[tuple[str, int, str | None]]) -> bool:
    return all(entry[2] is not None for entry in scope_stack if entry[0] == "class")


def python_public_class_path(
    scope_stack: list[tuple[str, int, str | None]],
) -> list[str] | None:
    class_entries = [entry[2] for entry in scope_stack if entry[0] == "class"]
    if not class_entries:
        return []
    if any(entry is None for entry in class_entries):
        return None
    return [entry for entry in class_entries if entry is not None]


def is_public_python_member_symbol(
    symbol: str,
    *,
    public_exports: set[str],
    public_classes: set[str],
) -> bool:
    if symbol in public_exports:
        return True
    if "." not in symbol:
        return False
    root_class, container = python_symbol_roots(symbol)
    return (
        container in public_exports
        or container in public_classes
        or root_class in public_exports
        or root_class in public_classes
    )


def match_python_member_renames(
    *,
    removed_symbols: list[str],
    added_symbols: list[str],
    removed_signatures: dict[str, list[PythonFunctionSignature]],
    added_signatures: dict[str, list[PythonFunctionSignature]],
) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    used_added: set[str] = set()
    for old_symbol in removed_symbols:
        if "." not in old_symbol:
            continue
        old_root, old_container = python_symbol_roots(old_symbol)
        old_sigs = removed_signatures.get(old_symbol, [])
        if not old_sigs:
            continue
        for new_symbol in added_symbols:
            if new_symbol in used_added or "." not in new_symbol:
                continue
            new_root, new_container = python_symbol_roots(new_symbol)
            if old_root != new_root or old_container != new_container:
                continue
            new_sigs = added_signatures.get(new_symbol, [])
            if not new_sigs:
                continue
            if not any(
                signatures_equivalent(old_sig, new_sig)
                for old_sig in old_sigs
                for new_sig in new_sigs
            ):
                continue
            pairs.append((old_symbol, new_symbol))
            used_added.add(new_symbol)
            break
    return pairs


def python_statement_anchor(line: str | None) -> str | None:
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


def infer_python_constructor_class_from_workspace(
    path: str,
    *,
    body_anchor: str | None,
    workspace_loader: WorkspaceLoader | None,
) -> str | None:
    class_path = infer_python_member_class_from_workspace(
        path,
        member_name="__init__",
        body_anchor=body_anchor,
        workspace_loader=workspace_loader,
    )
    if class_path is None or "." in class_path:
        return None
    return class_path


def infer_python_member_class_from_workspace(
    path: str,
    *,
    member_name: str,
    body_anchor: str | None,
    workspace_loader: WorkspaceLoader | None,
) -> str | None:
    lines = read_workspace_python_lines(path, workspace_loader=workspace_loader)
    if lines is None:
        return None
    candidates: list[str] = []
    scope_stack: list[tuple[str, int, str | None]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        indent = python_indent_level(line)
        if line.strip():
            while scope_stack and indent <= scope_stack[-1][1]:
                scope_stack.pop()
        class_match = PYTHON_PUBLIC_CLASS_PATTERN.search(line)
        if class_match and not line.lstrip().startswith("@"):
            class_name = class_match.group(1)
            scope_stack.append(
                ("class", indent, class_name if not class_name.startswith("_") else None)
            )
            index += 1
            continue
        if not PYTHON_DEF_START_PATTERN.search(line):
            index += 1
            continue
        signature_source, next_index = collect_python_signature_source(lines, index)
        def_match = PYTHON_PUBLIC_DEF_PATTERN.search(signature_source)
        if def_match and def_match.group(1) == member_name and indent > 0:
            next_body_line = (
                lines[next_index].strip()
                if next_index < len(lines) and lines[next_index].strip()
                else None
            )
            if python_class_scope_is_public(scope_stack):
                public_class_path = python_public_class_path(scope_stack)
                has_function_scope = any(entry[0] == "def" for entry in scope_stack)
                if (
                    public_class_path
                    and not has_function_scope
                    and (
                        body_anchor is None
                        or python_statement_anchor(next_body_line)
                        == python_statement_anchor(body_anchor)
                    )
                ):
                    candidates.append(".".join(public_class_path))
            else:
                scope_stack.append(("def", indent, None))
                index = next_index
                continue
        if def_match:
            scope_stack.append(("def", indent, None))
        index = next_index
    unique_candidates = sorted(set(candidates))
    return unique_candidates[0] if len(unique_candidates) == 1 else None


def has_ambiguous_python_constructor_match(
    path: str,
    *,
    body_anchor: str | None,
    workspace_loader: WorkspaceLoader | None,
) -> bool:
    lines = read_workspace_python_lines(path, workspace_loader=workspace_loader)
    if lines is None:
        return False
    candidates: list[str] = []
    current_top_level_class: str | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        is_top_level = is_python_top_level_statement(line)
        class_match = PYTHON_PUBLIC_CLASS_PATTERN.search(line) if is_top_level else None
        if class_match and not line.lstrip().startswith("@"):
            name = class_match.group(1)
            current_top_level_class = name if not name.startswith("_") else None
            index += 1
            continue
        if is_top_level and not class_match and line.strip():
            current_top_level_class = None
        if not PYTHON_DEF_START_PATTERN.search(line):
            index += 1
            continue
        signature_source, next_index = collect_python_signature_source(lines, index)
        def_match = PYTHON_PUBLIC_DEF_PATTERN.search(signature_source)
        if (
            current_top_level_class
            and def_match
            and def_match.group(1) == "__init__"
            and python_indent_level(line) > 0
        ):
            next_body_line = (
                lines[next_index].strip()
                if next_index < len(lines) and lines[next_index].strip()
                else None
            )
            if body_anchor is None or python_statement_anchor(
                next_body_line
            ) == python_statement_anchor(body_anchor):
                candidates.append(current_top_level_class)
        index = next_index
    return len(set(candidates)) > 1


def classify_nested_python_constructor_context(
    path: str,
    *,
    body_anchor: str | None,
    workspace_loader: WorkspaceLoader | None,
) -> str:
    lines = read_workspace_python_lines(path, workspace_loader=workspace_loader)
    if lines is None:
        return "unknown"
    stack: list[tuple[str, int, str | None]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        indent = python_indent_level(line)
        if line.strip():
            while stack and indent <= stack[-1][1]:
                stack.pop()
        class_match = PYTHON_PUBLIC_CLASS_PATTERN.search(line)
        if class_match and not line.lstrip().startswith("@"):
            name = class_match.group(1)
            stack.append(("class", indent, name if not name.startswith("_") else None))
            index += 1
            continue
        if not PYTHON_DEF_START_PATTERN.search(line):
            index += 1
            continue
        signature_source, next_index = collect_python_signature_source(lines, index)
        def_match = PYTHON_PUBLIC_DEF_PATTERN.search(signature_source)
        if def_match and def_match.group(1) == "__init__":
            next_body_line = (
                lines[next_index].strip()
                if next_index < len(lines) and lines[next_index].strip()
                else None
            )
            if body_anchor is None or python_statement_anchor(
                next_body_line
            ) == python_statement_anchor(body_anchor):
                public_class_path = python_public_class_path(stack)
                if any(entry[0] == "def" for entry in stack) or public_class_path is None:
                    return "nonpublic"
                if len(public_class_path) > 1:
                    return "public"
                return "unknown"
        if def_match:
            stack.append(("def", indent, None))
            index = next_index
        else:
            index += 1
    return "unknown"


def classify_nested_python_constructor_context_from_hunk(
    file_diff: FileDiff,
    *,
    change_index: int,
) -> str:
    current_indent = python_indent_level(file_diff.ordered_lines[change_index][1])
    if current_indent <= 4:
        return "unknown"
    public_class_depth = 0
    has_private_class_scope = False
    has_function_scope = False
    scope_indent = current_indent
    cursor = change_index - 1
    while cursor >= 0:
        candidate = file_diff.ordered_lines[cursor][1]
        if not candidate.strip():
            cursor -= 1
            continue
        candidate_indent = python_indent_level(candidate)
        if candidate_indent >= scope_indent:
            cursor -= 1
            continue
        class_match = PYTHON_PUBLIC_CLASS_PATTERN.search(candidate)
        if class_match and not candidate.lstrip().startswith("@"):
            if class_match.group(1).startswith("_"):
                has_private_class_scope = True
            else:
                public_class_depth += 1
            scope_indent = candidate_indent
        elif PYTHON_DEF_START_PATTERN.search(candidate):
            has_function_scope = True
            scope_indent = candidate_indent
        cursor -= 1
    if has_function_scope or has_private_class_scope:
        return "nonpublic"
    return "public" if public_class_depth > 1 else "unknown"
