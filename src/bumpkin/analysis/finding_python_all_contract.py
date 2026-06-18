import ast

from bumpkin.analysis.finding_python_surface_base import (
    PYTHON_ALL_EXPORT_START_PATTERN,
    PythonAllContract,
    WorkspaceLoader,
    collect_python_all_assignment,
    extract_python_possible_string_names,
    extract_python_string_names,
    is_python_top_level_statement,
    read_workspace_python_lines,
)


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
                for member in extract_python_possible_string_names(value)
                if not member.startswith("_")
            )
    return exports


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
            supported, values = extract_python_string_names(statement.value)
            if not supported:
                has_unsupported_all = True
                continue
            exports = set(values)
        elif isinstance(statement, ast.AugAssign) and isinstance(statement.op, ast.Add):
            supported, values = extract_python_string_names(statement.value)
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


def workspace_python_all_contract(
    path: str,
    *,
    workspace_loader: WorkspaceLoader | None,
) -> PythonAllContract | None:
    lines = read_workspace_python_lines(path, workspace_loader=workspace_loader)
    if lines is None:
        return None
    return extract_python_all_contract(lines)
