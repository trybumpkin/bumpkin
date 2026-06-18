from __future__ import annotations

from dataclasses import dataclass

from bumpkin.analysis import (
    finding_diff,
    finding_python_packaging,
    finding_python_signatures,
    finding_python_surface,
    finding_workspace,
)

_FileDiff = finding_diff.FileDiff
WorkspaceLoader = finding_workspace.WorkspaceLoader
_read_workspace_python_lines = finding_workspace.read_workspace_python_lines
PYTHON_DEF_START_PATTERN = finding_python_surface.PYTHON_DEF_START_PATTERN
PythonAllContract = finding_python_surface.PythonAllContract
PythonFunctionSignature = finding_python_signatures.PythonFunctionSignature
_allows_python_implicit_public_surface = (
    finding_python_surface.allows_python_implicit_public_surface
)
_extract_python_all_contract = finding_python_surface.extract_python_all_contract
_extract_python_implicit_public_names = finding_python_surface.extract_python_implicit_public_names
_extract_python_import_public_names = finding_python_surface.extract_python_import_public_names
_extract_python_local_public_names = finding_python_surface.extract_python_local_public_names
_extract_python_possible_all_exports = finding_python_surface.extract_python_possible_all_exports
_extract_python_public_import_bindings = (
    finding_python_surface.extract_python_public_import_bindings
)
_extract_python_public_names = finding_python_surface.extract_python_public_names
_extract_python_star_reexport_statements = (
    finding_python_surface.extract_python_star_reexport_statements
)
_python_indent_level = finding_python_surface.python_indent_level
_workspace_python_all_contract = finding_python_surface.workspace_python_all_contract
_workspace_python_api_reexport_names = finding_python_surface.workspace_python_api_reexport_names
_extract_python_signatures = finding_python_signatures.extract_python_signatures
_extract_python_classes = finding_python_signatures.extract_python_classes
_has_ambiguous_python_constructor_match = (
    finding_python_signatures.has_ambiguous_python_constructor_match
)
_classify_nested_python_constructor_context = (
    finding_python_signatures.classify_nested_python_constructor_context
)
_classify_nested_python_constructor_context_from_hunk = (
    finding_python_signatures.classify_nested_python_constructor_context_from_hunk
)
_extract_requires_python_floor = finding_python_packaging.extract_requires_python_floor
_is_supported_python_packaging_metadata_path = (
    finding_python_packaging.is_supported_python_packaging_metadata_path
)

PYTHON_EXTENSIONS = (".py", ".pyi", ".pyw")


@dataclass(slots=True)
class PythonDetectionContext:
    file_diff: _FileDiff
    removed_version_lines: list[str]
    added_version_lines: list[str]
    workspace_lines: list[str] | None
    workspace_api_reexport_names: set[str]
    removed_import_public_names: set[str]
    added_import_public_names: set[str]
    removed_local_public_names: set[str]
    added_local_public_names: set[str]
    removed_star_reexports: set[str]
    added_star_reexports: set[str]
    api_explicit_public_names: set[str] | None
    removed_all_contract: PythonAllContract
    added_all_contract: PythonAllContract
    removed_has_explicit_all: bool
    added_has_explicit_all: bool
    removed_all_exports: set[str]
    added_all_exports: set[str]
    workspace_all_contract: PythonAllContract | None
    allow_implicit_public_surface: bool
    partial_unresolved_all_exports: set[str]
    touched_all_assignment: bool
    unresolved_all_contract: bool
    touched_meaningful_code: bool
    unresolved_candidate_names: list[str]
    workspace_explicit_exports: set[str] | None
    removed_exports: set[str]
    added_exports: set[str]
    shared_public_exports: set[str]
    unreexported_local_public_exports: set[str]
    removed_import_bindings: dict[str, str]
    added_import_bindings: dict[str, str]
    workspace_public_names: set[str] | None
    workspace_public_classes: set[str]
    removed_signatures: dict[str, list[PythonFunctionSignature]]
    added_signatures: dict[str, list[PythonFunctionSignature]]
    removed_classes: set[str]
    added_classes: set[str]
    constructor_change_present: bool
    nested_constructor_change: bool
    nonpublic_nested_constructor_change: bool
    resolved_constructor_symbols: set[str]
    ambiguous_constructor_change: bool
    unresolved_constructor_change: bool


def is_python_path(path: str) -> bool:
    normalized = path.strip().lower()
    return normalized.endswith(PYTHON_EXTENSIONS)


def iter_python_version_source_lines(
    file_diff: _FileDiff,
    *,
    target_prefix: str,
) -> list[str]:
    return [line for prefix, line in file_diff.ordered_lines if prefix in {" ", target_prefix}]


def detect_python_packaging_floor_raise(
    file_diff: _FileDiff,
) -> tuple[tuple[int, ...], tuple[int, ...]] | None:
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
        return removed_floor, added_floor
    return None


def build_python_detection_context(
    file_diff: _FileDiff,
    *,
    workspace_loader: WorkspaceLoader | None,
) -> PythonDetectionContext:
    removed_version_lines = iter_python_version_source_lines(file_diff, target_prefix="-")
    added_version_lines = iter_python_version_source_lines(file_diff, target_prefix="+")
    workspace_lines = _read_workspace_python_lines(
        file_diff.path,
        workspace_loader=workspace_loader,
    )
    workspace_api_reexport_names = _workspace_python_api_reexport_names(
        file_diff.path,
        workspace_loader=workspace_loader,
    ) or set()
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
        if workspace_api_reexport_names & (removed_import_public_names | added_import_public_names):
            api_explicit_public_names.update(removed_import_public_names | added_import_public_names)
    removed_all_contract = _extract_python_all_contract(removed_version_lines)
    added_all_contract = _extract_python_all_contract(added_version_lines)
    removed_has_explicit_all = removed_all_contract.has_explicit and removed_all_contract.is_supported
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
            else set()
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
    touched_meaningful_code = any(
        stripped and not stripped.startswith("#")
        for stripped in (line.strip() for line in (*file_diff.added_lines, *file_diff.removed_lines))
    )
    unresolved_candidate_names = sorted(
        (
            _extract_python_implicit_public_names(
                removed_version_lines,
                path=file_diff.path,
                workspace_lines=workspace_lines,
                explicit_public_names=api_explicit_public_names,
                workspace_loader=workspace_loader,
            )
            | _extract_python_implicit_public_names(
                added_version_lines,
                path=file_diff.path,
                workspace_lines=workspace_lines,
                explicit_public_names=api_explicit_public_names,
                workspace_loader=workspace_loader,
            )
        )
        if unresolved_all_contract and allow_implicit_public_surface
        else set()
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
    removed_import_bindings = _extract_python_public_import_bindings(
        removed_version_lines,
        path=file_diff.path,
        workspace_lines=workspace_lines,
        explicit_public_names=removed_all_exports if removed_has_explicit_all else api_explicit_public_names,
        workspace_loader=workspace_loader,
    )
    added_import_bindings = _extract_python_public_import_bindings(
        added_version_lines,
        path=file_diff.path,
        workspace_lines=workspace_lines,
        explicit_public_names=added_all_exports if added_has_explicit_all else api_explicit_public_names,
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
                if candidate.strip() and _python_indent_level(candidate) > _python_indent_level(line):
                    next_body_line = candidate.strip()
                    break
                if candidate.strip() and _python_indent_level(candidate) <= _python_indent_level(line):
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
            shared_public_exports - (shared_local_public_exports - explicit_shared_local_public_exports)
        ) | (shared_local_public_exports & workspace_api_reexport_names)
    workspace_public_classes = workspace_public_names or set()

    return PythonDetectionContext(
        file_diff=file_diff,
        removed_version_lines=removed_version_lines,
        added_version_lines=added_version_lines,
        workspace_lines=workspace_lines,
        workspace_api_reexport_names=workspace_api_reexport_names,
        removed_import_public_names=removed_import_public_names,
        added_import_public_names=added_import_public_names,
        removed_local_public_names=removed_local_public_names,
        added_local_public_names=added_local_public_names,
        removed_star_reexports=removed_star_reexports,
        added_star_reexports=added_star_reexports,
        api_explicit_public_names=api_explicit_public_names,
        removed_all_contract=removed_all_contract,
        added_all_contract=added_all_contract,
        removed_has_explicit_all=removed_has_explicit_all,
        added_has_explicit_all=added_has_explicit_all,
        removed_all_exports=removed_all_exports,
        added_all_exports=added_all_exports,
        workspace_all_contract=workspace_all_contract,
        allow_implicit_public_surface=allow_implicit_public_surface,
        partial_unresolved_all_exports=partial_unresolved_all_exports,
        touched_all_assignment=touched_all_assignment,
        unresolved_all_contract=unresolved_all_contract,
        touched_meaningful_code=touched_meaningful_code,
        unresolved_candidate_names=unresolved_candidate_names,
        workspace_explicit_exports=workspace_explicit_exports,
        removed_exports=removed_exports,
        added_exports=added_exports,
        shared_public_exports=shared_public_exports,
        unreexported_local_public_exports=unreexported_local_public_exports,
        removed_import_bindings=removed_import_bindings,
        added_import_bindings=added_import_bindings,
        workspace_public_names=workspace_public_names,
        workspace_public_classes=workspace_public_classes,
        removed_signatures=removed_signatures,
        added_signatures=added_signatures,
        removed_classes=removed_classes,
        added_classes=added_classes,
        constructor_change_present=constructor_change_present,
        nested_constructor_change=nested_constructor_change,
        nonpublic_nested_constructor_change=nonpublic_nested_constructor_change,
        resolved_constructor_symbols=resolved_constructor_symbols,
        ambiguous_constructor_change=ambiguous_constructor_change,
        unresolved_constructor_change=unresolved_constructor_change,
    )
