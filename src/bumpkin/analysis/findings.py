from __future__ import annotations

import ast
import configparser
import re
from dataclasses import replace

from bumpkin.analysis import (
    finding_aggregation,
    finding_diff,
    finding_js_ts,
    finding_python_parameter_compat,
    finding_python_signatures,
    finding_python_surface,
    finding_types,
    finding_workspace,
)

aggregate_findings = finding_aggregation.aggregate_findings
AggregatedFindingResult = finding_types.AggregatedFindingResult
CONFIDENCE_ORDER = finding_types.CONFIDENCE_ORDER
DIFF_GIT_HEADER = finding_diff.DIFF_GIT_HEADER
Finding = finding_types.Finding
SEVERITY_ORDER = finding_types.SEVERITY_ORDER
WorkspaceLoader = finding_workspace.WorkspaceLoader
PYTHON_SOURCE_ROOT_NAMES = finding_workspace.PYTHON_SOURCE_ROOT_NAMES
_FileDiff = finding_diff.FileDiff
_parse_diff_files = finding_diff.parse_diff_files
build_filesystem_workspace_loader = finding_workspace.build_filesystem_workspace_loader
_read_workspace_python_lines = finding_workspace.read_workspace_python_lines
_python_package_root = finding_workspace.python_package_root
_python_module_candidates = finding_workspace.python_module_candidates
_python_relative_module_from_ancestor = finding_workspace.python_relative_module_from_ancestor
_match_export_renames = finding_js_ts.match_export_renames
_PythonAllContract = finding_python_surface.PythonAllContract
PYTHON_ALL_EXPORT_START_PATTERN = finding_python_surface.PYTHON_ALL_EXPORT_START_PATTERN
PYTHON_DEF_START_PATTERN = finding_python_surface.PYTHON_DEF_START_PATTERN
PYTHON_IMPORT_START_PATTERN = finding_python_surface.PYTHON_IMPORT_START_PATTERN
PYTHON_PUBLIC_ASSIGNMENT_PATTERN = finding_python_surface.PYTHON_PUBLIC_ASSIGNMENT_PATTERN
PYTHON_PUBLIC_CLASS_PATTERN = finding_python_surface.PYTHON_PUBLIC_CLASS_PATTERN
PYTHON_PUBLIC_DEF_PATTERN = finding_python_surface.PYTHON_PUBLIC_DEF_PATTERN
PYTHON_TYPE_CHECKING_PATTERN = finding_python_surface.PYTHON_TYPE_CHECKING_PATTERN
_allows_python_implicit_public_surface = (
    finding_python_surface.allows_python_implicit_public_surface
)
_collect_python_all_assignment = finding_python_surface.collect_python_all_assignment
_collect_python_import_statement = finding_python_surface.collect_python_import_statement
_collect_python_signature_source = finding_python_surface.collect_python_signature_source
_extract_python_all_contract = finding_python_surface.extract_python_all_contract
_extract_python_explicit_import_alias_names = (
    finding_python_surface.extract_python_explicit_import_alias_names
)
_extract_python_implicit_public_names = finding_python_surface.extract_python_implicit_public_names
_extract_python_import_public_names = finding_python_surface.extract_python_import_public_names
_extract_python_imported_names = finding_python_surface.extract_python_imported_names
_extract_python_local_public_names = finding_python_surface.extract_python_local_public_names
_extract_python_possible_all_exports = finding_python_surface.extract_python_possible_all_exports
_extract_python_public_import_bindings = (
    finding_python_surface.extract_python_public_import_bindings
)
_extract_python_public_names = finding_python_surface.extract_python_public_names
_extract_python_star_reexport_statements = (
    finding_python_surface.extract_python_star_reexport_statements
)
_has_python_explicit_public_import_alias = (
    finding_python_surface.has_python_explicit_public_import_alias
)
_is_obviously_internal_python_path = finding_python_surface.is_obviously_internal_python_path
_is_python_api_surface = finding_python_surface.is_python_api_surface
_is_python_public_reexport_statement = finding_python_surface.is_python_public_reexport_statement
_is_python_reexport_surface = finding_python_surface.is_python_reexport_surface
_is_python_top_level_statement = finding_python_surface.is_python_top_level_statement
_looks_like_python_import_only_facade = finding_python_surface.looks_like_python_import_only_facade
_looks_like_python_reexport_facade = finding_python_surface.looks_like_python_reexport_facade
_python_indent_level = finding_python_surface.python_indent_level
_split_top_level_params = finding_python_surface.split_top_level_params
_strip_python_inline_comment = finding_python_surface.strip_python_inline_comment
_workspace_python_all_contract = finding_python_surface.workspace_python_all_contract
_workspace_python_api_reexport_names = finding_python_surface.workspace_python_api_reexport_names
_FunctionSignature = finding_python_signatures.PythonFunctionSignature
_PythonParameterSpec = finding_python_parameter_compat.PythonParameterSpec
_signature_key = finding_python_signatures.signature_key
_signatures_equivalent = finding_python_signatures.signatures_equivalent
_python_symbol_roots = finding_python_signatures.python_symbol_roots
_python_class_scope_is_public = finding_python_signatures.python_class_scope_is_public
_python_public_class_path = finding_python_signatures.python_public_class_path
_is_public_python_member_symbol = finding_python_signatures.is_public_python_member_symbol
_match_python_member_renames = finding_python_signatures.match_python_member_renames
_python_statement_anchor = finding_python_signatures.python_statement_anchor
_infer_python_constructor_class_from_workspace = (
    finding_python_signatures.infer_python_constructor_class_from_workspace
)
_infer_python_member_class_from_workspace = (
    finding_python_signatures.infer_python_member_class_from_workspace
)
_has_ambiguous_python_constructor_match = (
    finding_python_signatures.has_ambiguous_python_constructor_match
)
_classify_nested_python_constructor_context = (
    finding_python_signatures.classify_nested_python_constructor_context
)
_classify_nested_python_constructor_context_from_hunk = (
    finding_python_signatures.classify_nested_python_constructor_context_from_hunk
)
_iter_python_version_lines = finding_python_signatures.iter_python_version_lines
_collect_python_signature_block = finding_python_signatures.collect_python_signature_block
_collect_python_decorator_names = finding_python_signatures.collect_python_decorator_names
_python_method_kind_from_decorators = finding_python_signatures.python_method_kind_from_decorators
_is_public_python_member_name = finding_python_signatures.is_public_python_member_name
_extract_python_signatures = finding_python_signatures.extract_python_signatures
_extract_python_classes = finding_python_signatures.extract_python_classes
_is_optional_param = finding_python_parameter_compat.is_optional_param
_normalize_python_annotation = finding_python_parameter_compat.normalize_python_annotation
_parse_python_parameter_specs = finding_python_parameter_compat.parse_python_parameter_specs
_same_python_parameter_surface = finding_python_parameter_compat.same_python_parameter_surface
_is_python_parameter_name_compatible = (
    finding_python_parameter_compat.is_python_parameter_name_compatible
)
_is_python_parameter_kind_compatible = (
    finding_python_parameter_compat.is_python_parameter_kind_compatible
)
_is_python_parameter_surface_compatible = (
    finding_python_parameter_compat.is_python_parameter_surface_compatible
)
_has_compatible_python_parameter_surface = (
    finding_python_parameter_compat.has_compatible_python_parameter_surface
)
_is_optional_widening = finding_python_parameter_compat.is_optional_widening
_is_requiredness_tightening = finding_python_parameter_compat.is_requiredness_tightening

JS_TS_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts")
PYTHON_EXTENSIONS = (".py", ".pyi", ".pyw")
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


def _reindex_findings(findings: list[Finding]) -> list[Finding]:
    return [
        replace(finding, id=f"{finding.rule}:{index}") for index, finding in enumerate(findings, 1)
    ]


def _is_python_path(path: str) -> bool:
    normalized = path.strip().lower()
    return normalized.endswith(PYTHON_EXTENSIONS)


def _python_packaging_metadata_kind(path: str) -> str | None:
    normalized = path.strip().replace("\\", "/").strip("/").lower()
    if not normalized:
        return None
    filename = normalized.rsplit("/", 1)[-1]
    if filename in {"pyproject.toml", "setup.cfg", "setup.py"}:
        return filename
    return None


def _is_supported_python_packaging_metadata_path(path: str) -> bool:
    return _python_packaging_metadata_kind(path) is not None


def _normalize_type(raw_type: str | None) -> str | None:
    if raw_type is None:
        return None
    cleaned = re.sub(r"\s+", " ", raw_type).strip()
    return cleaned or None


def _iter_python_version_source_lines(
    file_diff: _FileDiff,
    *,
    target_prefix: str,
) -> list[str]:
    return [line for prefix, line in file_diff.ordered_lines if prefix in {" ", target_prefix}]


def _extract_python_floor_from_constraint(constraint: str) -> tuple[int, ...] | None:
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


def _resolve_setup_py_string_value(
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


def _extract_setup_py_top_level_strings(
    module: ast.Module,
) -> tuple[dict[str, str], dict[str, str]]:
    constants: dict[str, str] = {}
    helpers: dict[str, str] = {}

    for statement in module.body:
        if isinstance(statement, ast.Assign):
            resolved_value = _resolve_setup_py_string_value(
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
            resolved_value = _resolve_setup_py_string_value(
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
            resolved_value = _resolve_setup_py_string_value(
                statement.body[0].value,
                constants=constants,
                helpers=helpers,
            )
            if resolved_value is not None:
                helpers[statement.name] = resolved_value

    return constants, helpers


def _extract_setup_py_python_requires_floor(lines: list[str]) -> tuple[int, ...] | None:
    source = "\n".join(lines)
    try:
        module = ast.parse(source)
    except SyntaxError:
        return None
    constants, helpers = _extract_setup_py_top_level_strings(module)
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
            value = _resolve_setup_py_string_value(
                keyword.value,
                constants=constants,
                helpers=helpers,
            )
            if not isinstance(value, str):
                continue
            floor = _extract_python_floor_from_constraint(value)
            if floor is not None:
                return floor
    return None


def _extract_setup_cfg_python_requires_floor(lines: list[str]) -> tuple[int, ...] | None:
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
            floor = _extract_python_floor_from_constraint(
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
            floor = _extract_python_floor_from_constraint(" ".join(value_lines).strip())
            if floor is not None:
                return floor
            continue
        if current_key == "python_requires" and line[:1].isspace():
            value_lines.append(line.strip())
            floor = _extract_python_floor_from_constraint(" ".join(value_lines).strip())
            if floor is not None:
                return floor
            continue
        current_key = None
        value_lines = []
    return None


def _extract_requires_python_floor(path: str, lines: list[str]) -> tuple[int, ...] | None:
    if not _is_supported_python_packaging_metadata_path(path):
        return None

    metadata_kind = _python_packaging_metadata_kind(path)
    if metadata_kind == "setup.cfg":
        return _extract_setup_cfg_python_requires_floor(lines)

    if metadata_kind == "setup.py":
        return _extract_setup_py_python_requires_floor(lines)

    current_section: str | None = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current_section = stripped.lower()
        match = REQUIRES_PYTHON_PATTERN.search(line)
        if match and current_section in {None, "[project]"}:
            floor = _extract_python_floor_from_constraint(match.group(1))
            if floor is not None:
                return floor
        poetry_match = POETRY_PYTHON_PATTERN.search(line)
        if poetry_match and current_section == "[tool.poetry.dependencies]":
            floor = _extract_python_floor_from_constraint(poetry_match.group(1))
            if floor is not None:
                return floor
    return None


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
    return finding_js_ts.run_js_ts_export_detection(
        diff_text,
        build_finding=_build_finding,
        normalize_type=_normalize_type,
        is_optional_widening=_is_optional_widening,
        is_requiredness_tightening=_is_requiredness_tightening,
    )


def detect_python_api_findings(
    diff_text: str,
    *,
    workspace_loader: WorkspaceLoader | None = None,
) -> list[Finding]:
    file_diffs = _parse_diff_files(diff_text)
    findings: list[Finding] = []
    counter = 0

    for file_diff in file_diffs:
        removed_version_lines = [
            line for prefix, line in file_diff.ordered_lines if prefix in {" ", "-"}
        ]
        added_version_lines = [
            line for prefix, line in file_diff.ordered_lines if prefix in {" ", "+"}
        ]
        removed_floor = _extract_requires_python_floor(file_diff.path, removed_version_lines)
        added_floor = _extract_requires_python_floor(file_diff.path, added_version_lines)
        if (
            _is_supported_python_packaging_metadata_path(file_diff.path)
            and removed_floor is not None
            and added_floor is not None
            and added_floor > removed_floor
        ):
            counter += 1
            findings.append(
                _build_finding(
                    severity="MAJOR",
                    rule="python_requires_floor_raised",
                    confidence="high",
                    title=(
                        "Raised supported Python floor: "
                        f"{'.'.join(map(str, removed_floor))} -> "
                        f"{'.'.join(map(str, added_floor))}"
                    ),
                    why=(
                        "Raising the minimum supported Python version breaks users on older "
                        "runtimes."
                    ),
                    path=file_diff.path,
                    snippet=next(
                        (
                            line
                            for line in file_diff.added_lines
                            if any(
                                marker in line.lower()
                                for marker in ("requires-python", "python_requires", "python =")
                            )
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
        workspace_lines = _read_workspace_python_lines(
            file_diff.path,
            workspace_loader=workspace_loader,
        )
        workspace_api_reexport_names = _workspace_python_api_reexport_names(
            file_diff.path,
            workspace_loader=workspace_loader,
        )
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
        workspace_all_contract = _workspace_python_all_contract(
            file_diff.path,
            workspace_loader=workspace_loader,
        )
        allow_implicit_public_surface = _allows_python_implicit_public_surface(
            file_diff.path,
            workspace_api_reexport_names=workspace_api_reexport_names,
        )
        partial_unresolved_all_exports: set[str] = (
            _extract_python_possible_all_exports(removed_version_lines)
            | _extract_python_possible_all_exports(added_version_lines)
            | (
                _extract_python_possible_all_exports(workspace_lines)
                if workspace_lines is not None
                else set[str]()
            )
        )
        touched_all_assignment = any(
            "__all__" in line for line in (*file_diff.added_lines, *file_diff.removed_lines)
        )
        unresolved_all_contract = any(
            contract is not None and contract.has_explicit and not contract.is_supported
            for contract in (
                removed_all_contract,
                added_all_contract,
                workspace_all_contract,
            )
        )
        if unresolved_all_contract:
            touched_meaningful_code = any(
                stripped and not stripped.startswith("#")
                for stripped in (
                    line.strip() for line in (*file_diff.added_lines, *file_diff.removed_lines)
                )
            )
            removed_candidate_names: set[str] = (
                _extract_python_implicit_public_names(
                    removed_version_lines,
                    path=file_diff.path,
                    workspace_lines=workspace_lines,
                    explicit_public_names=api_explicit_public_names,
                    workspace_loader=workspace_loader,
                )
                if allow_implicit_public_surface
                else set()
            )
            added_candidate_names: set[str] = (
                _extract_python_implicit_public_names(
                    added_version_lines,
                    path=file_diff.path,
                    workspace_lines=workspace_lines,
                    explicit_public_names=api_explicit_public_names,
                    workspace_loader=workspace_loader,
                )
                if allow_implicit_public_surface
                else set()
            )
            candidate_names = sorted(removed_candidate_names | added_candidate_names)
            if candidate_names or touched_all_assignment or touched_meaningful_code:
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
                workspace_loader=workspace_loader,
                allow_implicit_exports=allow_implicit_public_surface,
            )
        )
        removed_import_bindings = _extract_python_public_import_bindings(
            removed_version_lines,
            path=file_diff.path,
            workspace_lines=workspace_lines,
            explicit_public_names=removed_all_exports
            if removed_has_explicit_all
            else api_explicit_public_names,
            workspace_loader=workspace_loader,
        )
        added_exports = (
            added_all_exports
            if added_has_explicit_all
            else _extract_python_public_names(
                added_version_lines,
                path=file_diff.path,
                workspace_lines=workspace_lines,
                explicit_public_names=api_explicit_public_names,
                workspace_loader=workspace_loader,
                allow_implicit_exports=allow_implicit_public_surface,
            )
        )
        added_import_bindings = _extract_python_public_import_bindings(
            added_version_lines,
            path=file_diff.path,
            workspace_lines=workspace_lines,
            explicit_public_names=added_all_exports
            if added_has_explicit_all
            else api_explicit_public_names,
            workspace_loader=workspace_loader,
        )
        if workspace_explicit_exports is not None and not touched_all_assignment:
            if not removed_has_explicit_all:
                removed_exports = removed_exports & workspace_explicit_exports
            if not added_has_explicit_all:
                added_exports = added_exports & workspace_explicit_exports
        elif unresolved_all_contract and partial_unresolved_all_exports:
            removed_exports = removed_exports & partial_unresolved_all_exports
            added_exports = added_exports & partial_unresolved_all_exports
        workspace_public_names = (
            _extract_python_public_names(
                workspace_lines,
                path=file_diff.path,
                workspace_lines=workspace_lines,
                explicit_public_names=api_explicit_public_names,
                workspace_loader=workspace_loader,
                allow_implicit_exports=allow_implicit_public_surface,
            )
            if workspace_lines is not None
            else None
        )
        removed_signatures = _extract_python_signatures(
            file_diff,
            target_prefix="-",
            workspace_loader=workspace_loader,
        )
        added_signatures = _extract_python_signatures(
            file_diff,
            target_prefix="+",
            workspace_loader=workspace_loader,
        )
        removed_classes = _extract_python_classes(
            removed_version_lines,
            has_explicit_all=removed_has_explicit_all,
            explicit_exports=removed_all_exports,
            allow_implicit_classes=allow_implicit_public_surface,
        )
        added_classes = _extract_python_classes(
            added_version_lines,
            has_explicit_all=added_has_explicit_all,
            explicit_exports=added_all_exports,
            allow_implicit_classes=allow_implicit_public_surface,
        )
        if workspace_explicit_exports is not None and not touched_all_assignment:
            if not removed_has_explicit_all:
                removed_classes = removed_classes & workspace_explicit_exports
            if not added_has_explicit_all:
                added_classes = added_classes & workspace_explicit_exports
        elif unresolved_all_contract and partial_unresolved_all_exports:
            removed_classes = removed_classes & partial_unresolved_all_exports
            added_classes = added_classes & partial_unresolved_all_exports
        constructor_change_present = any(
            PYTHON_DEF_START_PATTERN.search(line)
            and "__init__" in line
            and _python_indent_level(line) > 0
            for line in (*file_diff.added_lines, *file_diff.removed_lines)
        )
        nested_constructor_change = False
        nonpublic_nested_constructor_change = False
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
                    workspace_loader=workspace_loader,
                )

            if context == "public":
                nested_constructor_change = True
                break
            if context == "nonpublic":
                nonpublic_nested_constructor_change = True

        resolved_constructor_symbols = {
            symbol
            for symbol in (set(removed_signatures) | set(added_signatures))
            if symbol.endswith(".__init__")
        }
        ambiguous_constructor_change = (
            constructor_change_present
            and _has_ambiguous_python_constructor_match(
                file_diff.path,
                body_anchor=None,
                workspace_loader=workspace_loader,
            )
        )
        unresolved_constructor_change = (
            constructor_change_present
            and not resolved_constructor_symbols
            and not nested_constructor_change
            and not nonpublic_nested_constructor_change
        )

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
            protected_local_export_contract = removed_all_exports & added_all_exports
            if workspace_explicit_exports is not None and not touched_all_assignment:
                protected_local_export_contract = (
                    protected_local_export_contract | workspace_explicit_exports
                )
            explicit_shared_local_public_exports = (
                shared_local_public_exports & protected_local_export_contract
            )
            unreexported_local_public_exports = (
                shared_local_public_exports
                - workspace_api_reexport_names
                - explicit_shared_local_public_exports
            )
            shared_public_exports = (
                shared_public_exports
                - (shared_local_public_exports - explicit_shared_local_public_exports)
            ) | (shared_local_public_exports & workspace_api_reexport_names)

        shared_import_binding_symbols = sorted(
            symbol
            for symbol in (set(removed_import_bindings) & set(added_import_bindings))
            if symbol in shared_public_exports
            and removed_import_bindings[symbol] != added_import_bindings[symbol]
        )
        for symbol in shared_import_binding_symbols:
            counter += 1
            findings.append(
                _build_finding(
                    severity="MAJOR",
                    rule="export_reexport_target_changed",
                    confidence="high",
                    title=f"Changed public Python re-export target: {symbol}",
                    why=(
                        "The public Python symbol still has the same exported name, but it now "
                        "resolves to a different imported target for downstream users."
                    ),
                    path=file_diff.path,
                    snippet=next(
                        (
                            line
                            for line in (*file_diff.added_lines, *file_diff.removed_lines)
                            if symbol in line
                        ),
                        file_diff.added_lines[0]
                        if file_diff.added_lines
                        else (file_diff.removed_lines[0] if file_diff.removed_lines else ""),
                    ),
                    counter=counter,
                )
            )
        removed_bound_public_names = removed_local_public_names | set(removed_import_bindings)
        added_bound_public_names = added_local_public_names | set(added_import_bindings)
        removed_explicit_binding_symbols = sorted(
            symbol
            for symbol in shared_public_exports
            if symbol in removed_bound_public_names and symbol not in added_bound_public_names
        )
        for symbol in removed_explicit_binding_symbols:
            counter += 1
            findings.append(
                _build_finding(
                    severity="MAJOR",
                    rule="export_symbol_removed",
                    confidence="high",
                    title=f"Removed public Python symbol(s): {symbol}",
                    why=(
                        "An explicitly exported Python symbol no longer resolves to a matching "
                        "public binding for downstream importers."
                    ),
                    path=file_diff.path,
                    snippet=next(
                        (
                            line
                            for line in (*file_diff.added_lines, *file_diff.removed_lines)
                            if symbol in line
                        ),
                        file_diff.added_lines[0]
                        if file_diff.added_lines
                        else (file_diff.removed_lines[0] if file_diff.removed_lines else ""),
                    ),
                    counter=counter,
                )
            )

        unresolved_api_import_binding_symbols = sorted(
            symbol
            for symbol in (set(removed_import_bindings) & set(added_import_bindings))
            if _is_python_api_surface(file_diff.path)
            and symbol not in shared_public_exports
            and removed_import_bindings[symbol] != added_import_bindings[symbol]
        )
        if unresolved_api_import_binding_symbols:
            counter += 1
            findings.append(
                _build_finding(
                    severity="MANUAL_REVIEW",
                    rule="python_api_module_import_binding_changed",
                    confidence="low",
                    title=(
                        "Changed api.py import-surface candidate requires manual review: "
                        f"{', '.join(unresolved_api_import_binding_symbols[:3])}"
                    ),
                    why=(
                        "This api.py module changed an imported symbol target without stronger "
                        "export evidence. Bumpkin cannot deterministically tell whether it is part "
                        "of the public submodule API or an internal wiring detail."
                    ),
                    path=file_diff.path,
                    snippet=next(
                        (
                            line
                            for line in (*file_diff.added_lines, *file_diff.removed_lines)
                            if any(
                                symbol in line for symbol in unresolved_api_import_binding_symbols
                            )
                        ),
                        file_diff.added_lines[0]
                        if file_diff.added_lines
                        else (file_diff.removed_lines[0] if file_diff.removed_lines else ""),
                    ),
                    counter=counter,
                )
            )
        stable_local_api_surface_names = {
            name
            for name in (removed_local_public_names & added_local_public_names)
            if name.lower() not in {"helper", "helpers", "util", "utils"}
        }
        explicit_api_import_alias_change = _is_python_api_surface(file_diff.path) and (
            _has_python_explicit_public_import_alias(
                removed_version_lines,
                path=file_diff.path,
            )
            or _has_python_explicit_public_import_alias(
                added_version_lines,
                path=file_diff.path,
            )
        )
        unresolved_api_import_surface_symbols = sorted(
            symbol
            for symbol in (removed_import_public_names ^ added_import_public_names)
            if _is_python_api_surface(file_diff.path)
            and workspace_explicit_exports is None
            and not removed_has_explicit_all
            and not added_has_explicit_all
            and (not stable_local_api_surface_names or explicit_api_import_alias_change)
            and symbol not in removed_exports
            and symbol not in added_exports
        )
        if unresolved_api_import_surface_symbols:
            counter += 1
            findings.append(
                _build_finding(
                    severity="MANUAL_REVIEW",
                    rule="python_api_module_import_surface_changed",
                    confidence="low",
                    title=(
                        "Changed api.py import-surface candidate requires manual review: "
                        f"{', '.join(unresolved_api_import_surface_symbols[:3])}"
                    ),
                    why=(
                        "This api.py module changed imported top-level symbols without stronger "
                        "export evidence. Bumpkin cannot deterministically tell whether those "
                        "imports are part of the public submodule API or internal wiring."
                    ),
                    path=file_diff.path,
                    snippet=next(
                        (
                            line
                            for line in (*file_diff.added_lines, *file_diff.removed_lines)
                            if any(
                                symbol in line for symbol in unresolved_api_import_surface_symbols
                            )
                        ),
                        file_diff.added_lines[0]
                        if file_diff.added_lines
                        else (file_diff.removed_lines[0] if file_diff.removed_lines else ""),
                    ),
                    counter=counter,
                )
            )
        workspace_public_classes = workspace_public_names or set()
        removed_member_only = sorted(
            symbol
            for symbol in (set(removed_signatures) - set(added_signatures))
            if _is_public_python_member_symbol(
                symbol,
                public_exports=shared_public_exports,
                public_classes=workspace_public_classes,
            )
        )
        added_member_only = sorted(
            symbol
            for symbol in (set(added_signatures) - set(removed_signatures))
            if _is_public_python_member_symbol(
                symbol,
                public_exports=shared_public_exports,
                public_classes=workspace_public_classes,
            )
        )
        member_rename_pairs = _match_python_member_renames(
            removed_symbols=removed_member_only,
            added_symbols=added_member_only,
            removed_signatures=removed_signatures,
            added_signatures=added_signatures,
        )
        renamed_removed_members = {old_name for old_name, _ in member_rename_pairs}
        renamed_added_members = {new_name for _, new_name in member_rename_pairs}
        for old_name, new_name in member_rename_pairs:
            counter += 1
            findings.append(
                _build_finding(
                    severity="MAJOR",
                    rule="export_symbol_renamed",
                    confidence="high",
                    title=f"Renamed public Python symbol: {old_name} -> {new_name}",
                    why=(
                        "Renaming a public Python method removes the previous supported "
                        "call path for downstream users."
                    ),
                    path=file_diff.path,
                    snippet=f"{old_name} -> {new_name}",
                    counter=counter,
                )
            )
        removed_member_only = [
            symbol for symbol in removed_member_only if symbol not in renamed_removed_members
        ]
        added_member_only = [
            symbol for symbol in added_member_only if symbol not in renamed_added_members
        ]
        if removed_member_only:
            counter += 1
            findings.append(
                _build_finding(
                    severity="MAJOR",
                    rule="export_symbol_removed",
                    confidence="high",
                    title=f"Removed public Python symbol(s): {', '.join(removed_member_only[:3])}",
                    why="Removing public Python methods is a breaking change for downstream users.",
                    path=file_diff.path,
                    snippet=next(
                        (
                            line
                            for line in file_diff.removed_lines
                            if any(
                                symbol.rsplit(".", 1)[-1] in line for symbol in removed_member_only
                            )
                        ),
                        file_diff.removed_lines[0] if file_diff.removed_lines else "",
                    ),
                    counter=counter,
                )
            )
        if added_member_only:
            counter += 1
            findings.append(
                _build_finding(
                    severity="MINOR",
                    rule="export_symbol_added",
                    confidence="high",
                    title=f"Added public Python symbol(s): {', '.join(added_member_only[:3])}",
                    why="Adding public Python methods expands the supported API surface.",
                    path=file_diff.path,
                    snippet=next(
                        (
                            line
                            for line in file_diff.added_lines
                            if any(
                                symbol.rsplit(".", 1)[-1] in line for symbol in added_member_only
                            )
                        ),
                        file_diff.added_lines[0] if file_diff.added_lines else "",
                    ),
                    counter=counter,
                )
            )
        shared_symbols = sorted(
            symbol
            for symbol in (set(removed_signatures) & set(added_signatures))
            if _is_public_python_member_symbol(
                symbol,
                public_exports=shared_public_exports,
                public_classes=workspace_public_classes,
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
            old_async = old_sigs[0].is_async
            new_async = new_sigs[0].is_async
            old_method_kind = old_sigs[0].method_kind
            new_method_kind = new_sigs[0].method_kind

            if (
                old_params == new_params
                and old_return == new_return
                and old_async == new_async
                and old_method_kind == new_method_kind
            ):
                continue

            if old_async != new_async:
                counter += 1
                findings.append(
                    _build_finding(
                        severity="MAJOR",
                        rule="export_async_contract_changed",
                        confidence="high",
                        title=f"Public Python async contract changed: {symbol}",
                        why=(
                            "Switching between async and sync changes how callers must invoke "
                            "the public Python callable."
                        ),
                        path=file_diff.path,
                        snippet=new_sigs[0].source,
                        counter=counter,
                    )
                )
                continue

            if old_method_kind != new_method_kind:
                counter += 1
                findings.append(
                    _build_finding(
                        severity="MAJOR",
                        rule="export_method_binding_changed",
                        confidence="high",
                        title=f"Public Python method binding changed: {symbol}",
                        why=(
                            "Changing whether a public method is bound as an instance, class, "
                            "static, or property-style accessor changes how downstream callers "
                            "must access it."
                        ),
                        path=file_diff.path,
                        snippet=new_sigs[0].source,
                        counter=counter,
                    )
                )
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

            if _has_compatible_python_parameter_surface(old_params, new_params):
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

        if ambiguous_constructor_change or unresolved_constructor_change:
            counter += 1
            findings.append(
                _build_finding(
                    severity="MANUAL_REVIEW",
                    rule="python_constructor_ambiguous",
                    confidence="low",
                    title="Changed Python constructor requires manual review",
                    why=(
                        "A public __init__ changed, but Bumpkin could not confidently resolve it "
                        "to a single class from the available analysis context."
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


def detect_semver_findings(
    diff_text: str,
    *,
    workspace_loader: WorkspaceLoader | None = None,
) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(detect_js_ts_export_findings(diff_text))
    findings.extend(
        detect_python_api_findings(
            diff_text,
            workspace_loader=workspace_loader,
        )
    )
    return _reindex_findings(findings)
