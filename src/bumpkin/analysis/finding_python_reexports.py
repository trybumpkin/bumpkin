import ast
from pathlib import Path

from bumpkin.analysis.finding_python_surface_base import (
    PYTHON_ALL_EXPORT_START_PATTERN,
    PYTHON_IMPORT_START_PATTERN,
    PYTHON_PUBLIC_ASSIGNMENT_PATTERN,
    PYTHON_TYPE_CHECKING_PATTERN,
    WorkspaceLoader,
    collect_python_all_assignment,
    collect_python_import_statement,
    is_python_api_surface,
    is_python_reexport_surface,
    is_python_top_level_statement,
    python_import_binding_name,
    python_module_candidates,
    python_package_root,
    python_relative_module_from_ancestor,
    read_workspace_python_lines,
)


def is_python_public_reexport_statement(statement: ast.stmt, *, path: str) -> bool:
    package_root = python_package_root(path)
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
    package_root = python_package_root(path)
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
            exported_name = python_import_binding_name(alias)
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
        package_root = python_package_root(path)
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

    module_candidates = python_module_candidates(path)
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
                lines := read_workspace_python_lines(
                    str(reexport_path), workspace_loader=workspace_loader
                )
            )
            is not None
        ]
        for reexport_path, lines in reexport_sources:
            relative_target = python_relative_module_from_ancestor(raw_path, reexport_path.parent)
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
