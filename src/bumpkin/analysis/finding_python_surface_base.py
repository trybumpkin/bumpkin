import ast
import re
from dataclasses import dataclass

from bumpkin.analysis import finding_workspace

WorkspaceLoader = finding_workspace.WorkspaceLoader
read_workspace_python_lines = finding_workspace.read_workspace_python_lines
python_module_candidates = finding_workspace.python_module_candidates
python_package_root = finding_workspace.python_package_root
python_relative_module_from_ancestor = finding_workspace.python_relative_module_from_ancestor

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


def extract_python_string_names(node: ast.AST | None) -> tuple[bool, set[str]]:
    if node is None:
        return False, set()
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True, {node.value}
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        exports: set[str] = set()
        for element in node.elts:
            supported, nested = extract_python_string_names(element)
            if not supported:
                return False, set()
            exports.update(nested)
        return True, exports
    return False, set()


def extract_python_possible_string_names(node: ast.AST | None) -> set[str]:
    supported, values = extract_python_string_names(node)
    if supported:
        return values
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return extract_python_possible_string_names(
            node.left
        ) | extract_python_possible_string_names(node.right)
    if isinstance(node, (ast.ListComp, ast.SetComp)) and len(node.generators) == 1:
        generator = node.generators[0]
        if generator.ifs:
            return set()
        if not isinstance(node.elt, ast.Name):
            return set()
        target = generator.target
        if not isinstance(target, ast.Name) or target.id != node.elt.id:
            return set()
        return extract_python_possible_string_names(generator.iter)
    return set()


def python_import_binding_name(alias: ast.alias) -> str | None:
    if alias.asname is not None:
        return alias.asname
    if not alias.name:
        return None
    return alias.name.split(".", 1)[0]


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
