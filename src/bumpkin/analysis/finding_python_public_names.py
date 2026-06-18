import ast

from bumpkin.analysis.finding_python_all_contract import extract_python_all_contract
from bumpkin.analysis.finding_python_reexports import (
    extract_python_explicit_import_alias_names,
    extract_python_imported_names,
    is_python_public_reexport_statement,
    looks_like_python_import_only_facade,
    looks_like_python_reexport_facade,
)
from bumpkin.analysis.finding_python_surface_base import (
    PYTHON_DEF_START_PATTERN,
    PYTHON_IMPORT_START_PATTERN,
    PYTHON_PUBLIC_ASSIGNMENT_PATTERN,
    PYTHON_PUBLIC_CLASS_PATTERN,
    PYTHON_PUBLIC_DEF_PATTERN,
    WorkspaceLoader,
    collect_python_import_statement,
    collect_python_signature_source,
    is_python_api_surface,
    is_python_top_level_statement,
    python_import_binding_name,
    split_top_level_params,
)


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
                exported_name = python_import_binding_name(alias)
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
