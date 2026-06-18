import re
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
    strip_python_inline_comment,
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
    root_class = symbol.split(".", 1)[0]
    container = symbol.rsplit(".", 1)[0]
    return root_class, container


def python_class_scope_is_public(scope_stack: list[tuple[str, int, str | None]]) -> bool:
    class_entries = [entry for entry in scope_stack if entry[0] == "class"]
    return all(entry[2] is not None for entry in class_entries)


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
            equivalent = any(
                signatures_equivalent(old_sig, new_sig)
                for old_sig in old_sigs
                for new_sig in new_sigs
            )
            if not equivalent:
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

        def_start = PYTHON_DEF_START_PATTERN.search(line)
        if not def_start:
            index += 1
            continue

        signature_source, next_index = collect_python_signature_source(lines, index)
        def_match = PYTHON_PUBLIC_DEF_PATTERN.search(signature_source)
        if def_match and def_match.group(1) == member_name and python_indent_level(line) > 0:
            next_body_line: str | None = None
            if next_index < len(lines):
                candidate = lines[next_index].strip()
                if candidate:
                    next_body_line = candidate
            if not python_class_scope_is_public(scope_stack):
                if def_match:
                    scope_stack.append(("def", indent, None))
                index = next_index
                continue
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
        if def_match:
            scope_stack.append(("def", indent, None))
        index = next_index

    unique_candidates = sorted(set(candidates))
    if len(unique_candidates) == 1:
        return unique_candidates[0]
    return None


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

        signature_source, next_index = collect_python_signature_source(lines, index)
        def_match = PYTHON_PUBLIC_DEF_PATTERN.search(signature_source)
        if (
            current_top_level_class
            and def_match
            and def_match.group(1) == "__init__"
            and python_indent_level(line) > 0
        ):
            next_body_line: str | None = None
            if next_index < len(lines):
                candidate = lines[next_index].strip()
                if candidate:
                    next_body_line = candidate
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
            class_name = class_match.group(1)
            stack.append(("class", indent, class_name if not class_name.startswith("_") else None))
            index += 1
            continue

        def_start = PYTHON_DEF_START_PATTERN.search(line)
        if not def_start:
            index += 1
            continue

        signature_source, next_index = collect_python_signature_source(lines, index)
        def_match = PYTHON_PUBLIC_DEF_PATTERN.search(signature_source)
        if def_match and def_match.group(1) == "__init__":
            next_body_line: str | None = None
            if next_index < len(lines):
                candidate = lines[next_index].strip()
                if candidate:
                    next_body_line = candidate
            if body_anchor is None or python_statement_anchor(
                next_body_line
            ) == python_statement_anchor(body_anchor):
                public_class_path = python_public_class_path(stack)
                has_function_scope = any(entry[0] == "def" for entry in stack)
                if has_function_scope:
                    return "nonpublic"
                if public_class_path is None:
                    return "nonpublic"
                if len(public_class_path) > 1:
                    return "public"
                return "unknown"

        if def_match:
            stack.append(("def", indent, None))
            index = next_index
            continue

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
            class_name = class_match.group(1)
            if not class_name.startswith("_"):
                public_class_depth += 1
            else:
                has_private_class_scope = True
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
    if has_private_class_scope:
        return "nonpublic"
    if public_class_depth > 1:
        return "public"
    return "unknown"


def iter_python_version_lines(
    file_diff: FileDiff,
    *,
    target_prefix: str,
) -> list[tuple[str, bool]]:
    active_prefixes = {" ", target_prefix}
    return [
        (line, prefix == target_prefix)
        for prefix, line in file_diff.ordered_lines
        if prefix in active_prefixes
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
        if not stripped:
            break
        if python_indent_level(line) != def_indent or not stripped.startswith("@"):
            break
        decorator_name = stripped[1:].split("(", 1)[0].strip()
        if decorator_name:
            decorators.add(decorator_name.split(".")[-1])
        cursor -= 1
    return decorators


def python_method_kind_from_decorators(decorators: set[str]) -> str:
    if "staticmethod" in decorators:
        return "staticmethod"
    if "classmethod" in decorators:
        return "classmethod"
    if "setter" in decorators:
        return "property-setter"
    if "deleter" in decorators:
        return "property-deleter"
    if "getter" in decorators:
        return "property-getter"
    if any(decorator == "property" or decorator.endswith("property") for decorator in decorators):
        return "property"
    return "instance"


def is_public_python_member_name(name: str) -> bool:
    if name == "__init__":
        return True
    if name.startswith("__") and name.endswith("__"):
        return True
    return not name.startswith("_")


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
            class_name = class_match.group(1)
            scope_stack.append(
                ("class", indent, class_name if not class_name.startswith("_") else None)
            )
            index += 1
            continue

        def_start = PYTHON_DEF_START_PATTERN.search(line)
        if not def_start:
            index += 1
            continue
        signature_start_index = index
        signature_source, _block_is_target, index = collect_python_signature_block(
            version_lines,
            index,
        )
        def_match = PYTHON_PUBLIC_DEF_PATTERN.search(signature_source)
        if not def_match:
            continue

        name = def_match.group(1)
        params = re.sub(r"\s+", "", def_match.group(2))
        return_type = _normalize_type(def_match.group(3))
        is_async = signature_source.lstrip().startswith("async def ")
        decorators = collect_python_decorator_names(version_lines, signature_start_index)
        next_body_line: str | None = None
        if index < len(version_lines):
            candidate = version_lines[index][0]
            if python_indent_level(candidate) > python_indent_level(line) and candidate.strip():
                next_body_line = candidate.strip()
        if python_indent_level(line) > 0 and not python_class_scope_is_public(scope_stack):
            continue
        public_class_path = python_public_class_path(scope_stack)
        has_function_scope = any(entry[0] == "def" for entry in scope_stack)
        if def_match:
            scope_stack.append(("def", indent, None))
        if python_indent_level(line) > 0:
            if not is_public_python_member_name(name):
                continue
            if name == "__init__" and python_indent_level(line) > 4:
                continue
            if public_class_path and not has_function_scope:
                symbol_name = ".".join([*public_class_path, name])
            elif name == "__init__":
                inferred_class = infer_python_constructor_class_from_workspace(
                    file_diff.path,
                    body_anchor=next_body_line,
                    workspace_loader=workspace_loader,
                )
                if not inferred_class:
                    continue
                symbol_name = f"{inferred_class}.__init__"
            else:
                inferred_class = infer_python_member_class_from_workspace(
                    file_diff.path,
                    member_name=name,
                    body_anchor=next_body_line,
                    workspace_loader=workspace_loader,
                )
                if not inferred_class:
                    continue
                symbol_name = f"{inferred_class}.{name}"
            method_kind = python_method_kind_from_decorators(decorators)
        else:
            if indent > 0:
                continue
            symbol_name = name
            method_kind = None

        signature = PythonFunctionSignature(
            name=symbol_name,
            params=params,
            return_type=return_type,
            is_async=is_async,
            source=signature_source,
            method_kind=method_kind,
        )
        signatures.setdefault(symbol_name, []).append(signature)

    return signatures


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
            def_start = PYTHON_DEF_START_PATTERN.search(line)
            if not def_start:
                index += 1
                continue
            signature_source, index = collect_python_signature_source(lines, index)
            if PYTHON_PUBLIC_DEF_PATTERN.search(signature_source):
                scope_stack.append(("def", indent, None))
            continue
        name = match.group(1)
        public_name = None
        if name.startswith("_") and not (
            has_explicit_all and explicit_exports is not None and name in explicit_exports
        ):
            public_name = None
        else:
            public_name = name

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
