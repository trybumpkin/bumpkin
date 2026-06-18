import ast
import re
from dataclasses import dataclass
from pathlib import Path

from bumpkin.analysis import finding_workspace

WorkspaceLoader = finding_workspace.WorkspaceLoader
_read_workspace_python_lines = finding_workspace.read_workspace_python_lines
_python_module_candidates = finding_workspace.python_module_candidates
_python_package_root = finding_workspace.python_package_root
_python_relative_module_from_ancestor = finding_workspace.python_relative_module_from_ancestor

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
class PythonAllContract:
    has_explicit: bool
    is_supported: bool
    exports: set[str]


def is_python_reexport_surface(path: str) -> bool:
    normalized = path.strip().replace("\\", "/").lower()
    return normalized.endswith(("__init__.py", "__init__.pyi"))


def is_python_api_surface(path: str) -> bool:
    normalized = path.strip().replace("\\", "/").lower()
    return normalized in {"api.py", "api.pyi"} or normalized.endswith(("/api.py", "/api.pyi"))


def is_obviously_internal_python_path(path: str) -> bool:
    normalized = path.strip().replace("\\", "/").strip("/").lower()
    if not normalized:
        return False
    parts = [part for part in normalized.split("/") if part]
    if not parts:
        return False
    filename = parts[-1]
    stem = filename.rsplit(".", 1)[0]
    internal_dirs = {
        "bench",
        "benches",
        "benchmark",
        "benchmarks",
        "docs",
        "doc",
        "example",
        "examples",
        "internal",
        "internals",
        "scripts",
        "test",
        "tests",
        "testing",
    }
    if any(part in internal_dirs or part.startswith("_") for part in parts[:-1]):
        return True
    internal_stems = {"conftest", "helper", "helpers", "internal", "util", "utils"}
    return stem in internal_stems or stem.startswith("test_") or stem.endswith("_test")


def allows_python_implicit_public_surface(
    path: str,
    *,
    workspace_api_reexport_names: set[str] | None,
) -> bool:
    if is_python_reexport_surface(path):
        return True
    if is_python_api_surface(path):
        return bool(workspace_api_reexport_names) or not is_obviously_internal_python_path(path)
    return not is_obviously_internal_python_path(path)


def python_indent_level(line: str) -> int:
    expanded = line.expandtabs(8)
    return len(expanded) - len(expanded.lstrip(" "))


def is_python_top_level_statement(line: str) -> bool:
    return python_indent_level(line) == 0


def strip_python_inline_comment(line: str) -> str:
    return line.split("#", 1)[0].rstrip()


def collect_python_signature_source(lines: list[str], start_index: int) -> tuple[str, int]:
    collected = [lines[start_index]]
    paren_depth = lines[start_index].count("(") - lines[start_index].count(")")
    cursor = start_index + 1

    while cursor < len(lines):
        stripped = strip_python_inline_comment(collected[-1]).strip()
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


def collect_python_all_assignment(lines: list[str], start_index: int) -> tuple[str, int]:
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


def collect_python_import_statement(lines: list[str], start_index: int) -> tuple[str, int]:
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


def _extract_python_possible_string_names(node: ast.AST | None) -> set[str]:
    supported, values = _extract_python_string_names(node)
    if supported:
        return values
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _extract_python_possible_string_names(
            node.left
        ) | _extract_python_possible_string_names(node.right)
    if isinstance(node, (ast.ListComp, ast.SetComp)) and len(node.generators) == 1:
        generator = node.generators[0]
        if generator.ifs:
            return set()
        if not isinstance(node.elt, ast.Name):
            return set()
        target = generator.target
        if not isinstance(target, ast.Name) or target.id != node.elt.id:
            return set()
        return _extract_python_possible_string_names(generator.iter)
    return set()


def extract_python_possible_all_exports(lines: list[str]) -> set[str]:
    exports: set[str] = set()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not is_python_top_level_statement(line):
            index += 1
            continue
        match = PYTHON_ALL_EXPORT_START_PATTERN.search(line)
        if not match:
            index += 1
            continue
        assignment_source, index = collect_python_all_assignment(lines, index)
        try:
            module = ast.parse(assignment_source)
        except SyntaxError:
            continue
        if len(module.body) != 1:
            continue
        statement = module.body[0]
        if isinstance(statement, (ast.Assign, ast.AnnAssign)) or (
            isinstance(statement, ast.AugAssign) and isinstance(statement.op, ast.Add)
        ):
            value = statement.value
            exports.update(
                member
                for member in _extract_python_possible_string_names(value)
                if not member.startswith("_")
            )
    return exports


def _python_import_binding_name(alias: ast.alias) -> str | None:
    if alias.asname is not None:
        return alias.asname
    if not alias.name:
        return None
    return alias.name.split(".", 1)[0]


def is_python_public_reexport_statement(statement: ast.stmt, *, path: str) -> bool:
    package_root = _python_package_root(path)
    return (
        isinstance(statement, ast.ImportFrom)
        and (
            statement.level > 0
            or is_python_api_surface(path)
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
        and any(
            (
                is_python_api_surface(path)
                or (
                    package_root is not None
                    and (alias.name == package_root or alias.name.startswith(f"{package_root}."))
                )
            )
            for alias in statement.names
        )
    )


def extract_python_imported_names(statement_source: str, *, path: str) -> set[str]:
    try:
        module = ast.parse(statement_source)
    except SyntaxError:
        return set()
    if len(module.body) != 1:
        return set()

    statement = module.body[0]
    exports: set[str] = set()
    package_root = _python_package_root(path)
    if isinstance(statement, ast.ImportFrom) and is_python_public_reexport_statement(
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
            if not (
                is_python_api_surface(path)
                or (
                    package_root is not None
                    and (alias.name == package_root or alias.name.startswith(f"{package_root}."))
                )
            ):
                continue
            exported_name = _python_import_binding_name(alias)
            if exported_name is None:
                continue
            if not exported_name.startswith("_"):
                exports.add(exported_name)
    return exports


def extract_python_explicit_import_alias_names(statement_source: str, *, path: str) -> set[str]:
    try:
        module = ast.parse(statement_source)
    except SyntaxError:
        return set()
    if len(module.body) != 1:
        return set()

    statement = module.body[0]
    exports: set[str] = set()
    if isinstance(statement, ast.ImportFrom) and is_python_public_reexport_statement(
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
            if alias.asname is None or not (
                is_python_api_surface(path)
                or (
                    package_root is not None
                    and (alias.name == package_root or alias.name.startswith(f"{package_root}."))
                )
            ):
                continue
            if not alias.asname.startswith("_"):
                exports.add(alias.asname)
    return exports


def has_python_explicit_public_import_alias(lines: list[str], *, path: str) -> bool:
    index = 0
    while index < len(lines):
        line = lines[index]
        if not is_python_top_level_statement(line):
            index += 1
            continue
        if not PYTHON_IMPORT_START_PATTERN.search(line):
            index += 1
            continue

        statement_source, index = collect_python_import_statement(lines, index)
        try:
            module = ast.parse(statement_source)
        except SyntaxError:
            continue
        if len(module.body) != 1:
            continue

        statement = module.body[0]
        if not is_python_public_reexport_statement(statement, path=path):
            continue
        if isinstance(statement, ast.ImportFrom) and any(
            alias.asname is not None and not alias.asname.startswith("_")
            for alias in statement.names
            if alias.name != "*"
        ):
            return True
    return False


def extract_python_star_reexport_statements(lines: list[str], *, path: str) -> set[str]:
    statements: set[str] = set()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not is_python_top_level_statement(line):
            index += 1
            continue
        if not PYTHON_IMPORT_START_PATTERN.search(line):
            index += 1
            continue
        statement_source, index = collect_python_import_statement(lines, index)
        try:
            module = ast.parse(statement_source)
        except SyntaxError:
            continue
        if len(module.body) != 1:
            continue
        statement = module.body[0]
        if not is_python_public_reexport_statement(statement, path=path):
            continue
        if isinstance(statement, ast.ImportFrom) and any(
            alias.name == "*" for alias in statement.names
        ):
            statements.add(statement_source)
    return statements


def workspace_python_api_reexport_names(
    path: str,
    *,
    workspace_loader: WorkspaceLoader | None,
) -> set[str] | None:
    raw_path = Path(path.strip())
    if raw_path.name.lower().startswith("__init__.py"):
        return None

    module_candidates = _python_module_candidates(path)
    exports: set[str] = set()
    for ancestor_dir in raw_path.parents:
        if str(ancestor_dir) in {"", "."}:
            continue
        reexport_candidates = (
            (
                ancestor_dir / "__init__.pyi",
                ancestor_dir / "__init__.py",
                ancestor_dir / "api.pyi",
                ancestor_dir / "api.py",
            )
            if raw_path.suffix.lower() == ".pyi"
            else (
                ancestor_dir / "__init__.py",
                ancestor_dir / "__init__.pyi",
                ancestor_dir / "api.py",
                ancestor_dir / "api.pyi",
            )
        )
        reexport_sources = [
            (reexport_path, lines)
            for reexport_path in reexport_candidates
            if (
                lines := _read_workspace_python_lines(
                    str(reexport_path), workspace_loader=workspace_loader
                )
            )
            is not None
        ]
        for reexport_path, lines in reexport_sources:
            relative_target = _python_relative_module_from_ancestor(raw_path, reexport_path.parent)
            index = 0
            while index < len(lines):
                line = lines[index]
                if not is_python_top_level_statement(line):
                    index += 1
                    continue
                if not PYTHON_IMPORT_START_PATTERN.search(line):
                    index += 1
                    continue

                statement_source, index = collect_python_import_statement(lines, index)
                try:
                    module = ast.parse(statement_source)
                except SyntaxError:
                    continue
                if len(module.body) != 1 or not isinstance(module.body[0], ast.ImportFrom):
                    continue

                statement = module.body[0]
                target_module = statement.module or ""
                is_module_reexport = (
                    statement.level > 0
                    and relative_target is not None
                    and target_module == relative_target
                ) or (statement.module is not None and target_module in module_candidates)
                if not is_module_reexport:
                    continue
                if any(alias.name == "*" for alias in statement.names):
                    return None
                exports.update(alias.name for alias in statement.names if alias.name != "*")

    return exports


def looks_like_python_import_only_facade(lines: list[str]) -> bool:
    index = 0
    while index < len(lines):
        line = lines[index]
        if not is_python_top_level_statement(line):
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
            _, index = collect_python_import_statement(lines, index)
            continue
        if PYTHON_ALL_EXPORT_START_PATTERN.search(line):
            _, index = collect_python_all_assignment(lines, index)
            continue
        assignment_match = PYTHON_PUBLIC_ASSIGNMENT_PATTERN.search(line)
        if assignment_match:
            name = assignment_match.group(1)
            if name.startswith("__") and name.endswith("__"):
                index += 1
                continue
        return False
    return True


def looks_like_python_reexport_facade(
    lines: list[str],
    *,
    path: str,
    workspace_lines: list[str] | None = None,
    workspace_loader: WorkspaceLoader | None = None,
) -> bool:
    if is_python_reexport_surface(path):
        return True
    if not is_python_api_surface(path.strip().replace("\\", "/").strip("/").lower()):
        return False
    api_reexport_names = workspace_python_api_reexport_names(
        path,
        workspace_loader=workspace_loader,
    )
    if api_reexport_names is None or api_reexport_names:
        return True
    candidate_lines = workspace_lines if workspace_lines is not None else lines
    return looks_like_python_import_only_facade(candidate_lines)


def workspace_python_all_contract(
    path: str,
    *,
    workspace_loader: WorkspaceLoader | None,
) -> PythonAllContract | None:
    lines = _read_workspace_python_lines(path, workspace_loader=workspace_loader)
    if lines is None:
        return None
    return extract_python_all_contract(lines)


def extract_python_all_contract(lines: list[str]) -> PythonAllContract:
    exports: set[str] = set()
    has_explicit_all = False
    has_unsupported_all = False
    index = 0
    while index < len(lines):
        line = lines[index]
        if not is_python_top_level_statement(line):
            index += 1
            continue
        match = PYTHON_ALL_EXPORT_START_PATTERN.search(line)
        if not match:
            index += 1
            continue
        has_explicit_all = True
        assignment_source, index = collect_python_all_assignment(lines, index)
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
            exports = set(values)
        elif isinstance(statement, ast.AugAssign) and isinstance(statement.op, ast.Add):
            supported, values = _extract_python_string_names(statement.value)
            if not supported:
                has_unsupported_all = True
                continue
            if operator == "=":
                exports = set(values)
            else:
                exports.update(values)
        else:
            has_unsupported_all = True
    if has_unsupported_all:
        return PythonAllContract(
            has_explicit=has_explicit_all,
            is_supported=False,
            exports=set(),
        )
    return PythonAllContract(
        has_explicit=has_explicit_all,
        is_supported=True,
        exports=exports,
    )


def split_top_level_params(params: str) -> list[str]:
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


def extract_python_implicit_public_names(
    lines: list[str],
    *,
    path: str,
    workspace_lines: list[str] | None = None,
    explicit_public_names: set[str] | None = None,
    workspace_loader: WorkspaceLoader | None = None,
) -> set[str]:
    exports: set[str] = set()
    candidate_lines = workspace_lines if workspace_lines is not None else lines
    allow_reexport_imports = looks_like_python_reexport_facade(
        lines,
        path=path,
        workspace_lines=workspace_lines,
        workspace_loader=workspace_loader,
    )
    import_only_api_facade = looks_like_python_import_only_facade(
        candidate_lines
    ) and is_python_api_surface(path)

    index = 0
    while index < len(lines):
        line = lines[index]
        if not is_python_top_level_statement(line):
            index += 1
            continue
        def_start = PYTHON_DEF_START_PATTERN.search(line)
        if def_start:
            signature_source, index = collect_python_signature_source(lines, index)
            def_match = PYTHON_PUBLIC_DEF_PATTERN.search(signature_source)
        else:
            def_match = None
        if def_match:
            name = def_match.group(1)
            params = split_top_level_params(def_match.group(2))
            if name.startswith("_") and (
                explicit_public_names is None or name not in explicit_public_names
            ):
                continue
            if params and params[0].strip() in {"self", "cls"}:
                continue
            exports.add(name)
            continue

        class_match = PYTHON_PUBLIC_CLASS_PATTERN.search(line)
        if class_match:
            name = class_match.group(1)
            if not name.startswith("_") or (
                explicit_public_names is not None and name in explicit_public_names
            ):
                exports.add(name)
            index += 1
            continue

        if allow_reexport_imports and PYTHON_IMPORT_START_PATTERN.search(line):
            statement_source, index = collect_python_import_statement(lines, index)
            explicit_alias_names = (
                extract_python_explicit_import_alias_names(
                    statement_source,
                    path=path,
                )
                if import_only_api_facade or explicit_public_names is not None
                else set[str]()
            )
            exports.update(
                name
                for name in extract_python_imported_names(statement_source, path=path)
                if (
                    import_only_api_facade
                    or explicit_public_names is None
                    or name in explicit_public_names
                    or name in explicit_alias_names
                )
            )
            continue

        assignment_match = PYTHON_PUBLIC_ASSIGNMENT_PATTERN.search(line)
        if assignment_match:
            name = assignment_match.group(1)
            if name != "__all__" and (
                not name.startswith("_")
                or (explicit_public_names is not None and name in explicit_public_names)
            ):
                exports.add(name)
        index += 1

    return exports


def extract_python_local_public_names(lines: list[str], *, path: str) -> set[str]:
    exports: set[str] = set()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not is_python_top_level_statement(line):
            index += 1
            continue
        def_start = PYTHON_DEF_START_PATTERN.search(line)
        if def_start:
            signature_source, index = collect_python_signature_source(lines, index)
            def_match = PYTHON_PUBLIC_DEF_PATTERN.search(signature_source)
        else:
            def_match = None
        if def_match:
            name = def_match.group(1)
            params = split_top_level_params(def_match.group(2))
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


def extract_python_public_names(
    lines: list[str],
    *,
    path: str,
    workspace_lines: list[str] | None = None,
    explicit_public_names: set[str] | None = None,
    workspace_loader: WorkspaceLoader | None = None,
    allow_implicit_exports: bool = True,
) -> set[str]:
    all_contract = extract_python_all_contract(lines)
    if all_contract.has_explicit and all_contract.is_supported:
        return all_contract.exports
    if not allow_implicit_exports:
        return set()
    return extract_python_implicit_public_names(
        lines,
        path=path,
        workspace_lines=workspace_lines,
        explicit_public_names=explicit_public_names,
        workspace_loader=workspace_loader,
    )


def extract_python_import_public_names(lines: list[str], *, path: str) -> set[str]:
    exports: set[str] = set()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not is_python_top_level_statement(line):
            index += 1
            continue
        if not PYTHON_IMPORT_START_PATTERN.search(line):
            index += 1
            continue
        statement_source, index = collect_python_import_statement(lines, index)
        exports.update(extract_python_imported_names(statement_source, path=path))
    return exports


def extract_python_public_import_bindings(
    lines: list[str],
    *,
    path: str,
    workspace_lines: list[str] | None = None,
    explicit_public_names: set[str] | None = None,
    workspace_loader: WorkspaceLoader | None = None,
) -> dict[str, str]:
    bindings: dict[str, str] = {}
    candidate_lines = workspace_lines if workspace_lines is not None else lines
    allow_reexport_imports = looks_like_python_reexport_facade(
        lines,
        path=path,
        workspace_lines=workspace_lines,
        workspace_loader=workspace_loader,
    )
    import_only_api_facade = looks_like_python_import_only_facade(
        candidate_lines
    ) and is_python_api_surface(path)
    allow_api_import_bindings = allow_reexport_imports or is_python_api_surface(path)

    index = 0
    while index < len(lines):
        line = lines[index]
        if not is_python_top_level_statement(line):
            index += 1
            continue
        if not (allow_api_import_bindings and PYTHON_IMPORT_START_PATTERN.search(line)):
            index += 1
            continue
        if not import_only_api_facade and explicit_public_names is None:
            index += 1
            continue

        statement_source, index = collect_python_import_statement(lines, index)
        try:
            module = ast.parse(statement_source)
        except SyntaxError:
            continue
        if len(module.body) != 1:
            continue

        statement = module.body[0]
        if not is_python_public_reexport_statement(statement, path=path):
            continue

        explicit_alias_names = (
            extract_python_explicit_import_alias_names(
                statement_source,
                path=path,
            )
            if import_only_api_facade or explicit_public_names is not None
            else set[str]()
        )
        if isinstance(statement, ast.ImportFrom):
            module_ref = "." * statement.level + (statement.module or "")
            for alias in statement.names:
                if alias.name == "*":
                    continue
                exported_name = alias.asname or alias.name
                if (
                    not import_only_api_facade
                    and explicit_public_names is not None
                    and exported_name not in explicit_public_names
                    and exported_name not in explicit_alias_names
                ):
                    continue
                bindings[exported_name] = f"{module_ref}:{alias.name}"
        elif isinstance(statement, ast.Import):
            for alias in statement.names:
                exported_name = _python_import_binding_name(alias)
                if exported_name is None:
                    continue
                if (
                    not import_only_api_facade
                    and explicit_public_names is not None
                    and exported_name not in explicit_public_names
                    and exported_name not in explicit_alias_names
                ):
                    continue
                bindings[exported_name] = alias.name

    return bindings
