import ast
import configparser
import re

REQUIRES_PYTHON_PATTERN = re.compile(
    r"""^\s*requires-python\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE,
)
SETUP_CFG_PYTHON_REQUIRES_PATTERN = re.compile(
    r"""^\s*python_requires\s*=\s*["']?([^"'\n]+)["']?""",
    re.IGNORECASE,
)
SETUP_PY_PYTHON_REQUIRES_PATTERN = re.compile(
    r"""^\s*python_requires\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE,
)
POETRY_PYTHON_PATTERN = re.compile(
    r"""^\s*python\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE,
)


def python_packaging_metadata_kind(path: str) -> str | None:
    normalized = path.strip().replace("\\", "/").strip("/").lower()
    if not normalized:
        return None
    filename = normalized.rsplit("/", 1)[-1]
    if filename in {"pyproject.toml", "setup.cfg", "setup.py"}:
        return filename
    return None


def is_supported_python_packaging_metadata_path(path: str) -> bool:
    return python_packaging_metadata_kind(path) is not None


def extract_python_floor_from_constraint(constraint: str) -> tuple[int, ...] | None:
    match = re.search(
        r"(?P<op>>=|>|~=|\^|==)\s*(?P<version>\d+(?:\.\d+)*)(?:\.\*)?",
        constraint,
    )
    if not match:
        return None
    parts = [int(part) for part in match.group("version").split(".")]
    if match.group("op") == ">":
        parts[-1] += 1
    return tuple(parts)


def resolve_setup_py_string_value(
    node: ast.AST | None,
    *,
    constants: dict[str, str],
    helpers: dict[str, str],
) -> str | None:
    if node is None:
        return None
    try:
        value = ast.literal_eval(node)
    except (ValueError, SyntaxError):
        value = None
    if isinstance(value, str):
        return value
    if isinstance(node, ast.Name):
        return constants.get(node.id) or helpers.get(node.id)
    if (
        isinstance(node, ast.Call)
        and not node.args
        and not node.keywords
        and isinstance(node.func, ast.Name)
    ):
        return helpers.get(node.func.id)
    return None


def extract_setup_py_top_level_strings(
    module: ast.Module,
) -> tuple[dict[str, str], dict[str, str]]:
    constants: dict[str, str] = {}
    helpers: dict[str, str] = {}

    for statement in module.body:
        if isinstance(statement, ast.Assign):
            resolved_value = resolve_setup_py_string_value(
                statement.value,
                constants=constants,
                helpers=helpers,
            )
            if resolved_value is None:
                continue
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = resolved_value
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            resolved_value = resolve_setup_py_string_value(
                statement.value,
                constants=constants,
                helpers=helpers,
            )
            if resolved_value is not None:
                constants[statement.target.id] = resolved_value
        elif isinstance(statement, ast.FunctionDef):
            if statement.args.args or statement.args.kwonlyargs:
                continue
            if statement.args.vararg or statement.args.kwarg:
                continue
            if len(statement.body) != 1 or not isinstance(statement.body[0], ast.Return):
                continue
            resolved_value = resolve_setup_py_string_value(
                statement.body[0].value,
                constants=constants,
                helpers=helpers,
            )
            if resolved_value is not None:
                helpers[statement.name] = resolved_value

    return constants, helpers


def extract_setup_py_python_requires_floor(lines: list[str]) -> tuple[int, ...] | None:
    source = "\n".join(lines)
    try:
        module = ast.parse(source)
    except SyntaxError:
        return None
    constants, helpers = extract_setup_py_top_level_strings(module)
    for node in ast.walk(module):
        if not isinstance(node, ast.Call):
            continue
        func_name = None
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            func_name = node.func.attr
        if func_name != "setup":
            continue
        for keyword in node.keywords:
            if keyword.arg != "python_requires":
                continue
            value = resolve_setup_py_string_value(
                keyword.value,
                constants=constants,
                helpers=helpers,
            )
            if not isinstance(value, str):
                continue
            floor = extract_python_floor_from_constraint(value)
            if floor is not None:
                return floor
    return None


def extract_setup_cfg_python_requires_floor(lines: list[str]) -> tuple[int, ...] | None:
    source = "\n".join(lines)
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(source)
    except (configparser.Error, TypeError, ValueError):
        parser = None
    if parser is not None:
        for section_name in ("options", "metadata"):
            if not parser.has_option(section_name, "python_requires"):
                continue
            floor = extract_python_floor_from_constraint(
                parser.get(section_name, "python_requires")
            )
            if floor is not None:
                return floor

    current_key: str | None = None
    value_lines: list[str] = []
    for line in lines:
        match = SETUP_CFG_PYTHON_REQUIRES_PATTERN.search(line)
        if match:
            current_key = "python_requires"
            value_lines = [match.group(1).strip()]
            floor = extract_python_floor_from_constraint(" ".join(value_lines).strip())
            if floor is not None:
                return floor
            continue
        if current_key == "python_requires" and line[:1].isspace():
            value_lines.append(line.strip())
            floor = extract_python_floor_from_constraint(" ".join(value_lines).strip())
            if floor is not None:
                return floor
            continue
        current_key = None
        value_lines = []
    return None


def extract_requires_python_floor(path: str, lines: list[str]) -> tuple[int, ...] | None:
    if not is_supported_python_packaging_metadata_path(path):
        return None

    metadata_kind = python_packaging_metadata_kind(path)
    if metadata_kind == "setup.cfg":
        return extract_setup_cfg_python_requires_floor(lines)

    if metadata_kind == "setup.py":
        return extract_setup_py_python_requires_floor(lines)

    current_section: str | None = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current_section = stripped.lower()
        match = REQUIRES_PYTHON_PATTERN.search(line)
        if match and current_section in {None, "[project]"}:
            floor = extract_python_floor_from_constraint(match.group(1))
            if floor is not None:
                return floor
        poetry_match = POETRY_PYTHON_PATTERN.search(line)
        if poetry_match and current_section == "[tool.poetry.dependencies]":
            floor = extract_python_floor_from_constraint(poetry_match.group(1))
            if floor is not None:
                return floor
    return None
