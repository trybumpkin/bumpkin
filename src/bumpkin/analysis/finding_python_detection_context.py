from __future__ import annotations

from dataclasses import dataclass

from bumpkin.analysis import (
    finding_diff,
    finding_python_packaging,
    finding_python_signatures,
    finding_python_surface,
    finding_workspace,
)
from bumpkin.analysis.finding_python_detection_context_helpers import (
    build_constructor_context as _build_constructor_context,
)
from bumpkin.analysis.finding_python_detection_context_helpers import (
    build_surface_context as _build_surface_context,
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
    added_version_lines = [line for prefix, line in file_diff.ordered_lines if prefix in {" ", "+"}]
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
    values = _build_surface_context(file_diff, workspace_loader=workspace_loader)
    constructor_values = _build_constructor_context(
        file_diff,
        workspace_loader=workspace_loader,
        removed_signatures=values["removed_signatures"],
        added_signatures=values["added_signatures"],
        removed_exports=values["removed_exports"],
        added_exports=values["added_exports"],
        workspace_api_reexport_names=values["workspace_api_reexport_names"],
        removed_local_public_names=values["removed_local_public_names"],
        added_local_public_names=values["added_local_public_names"],
        removed_all_exports=values["removed_all_exports"],
        added_all_exports=values["added_all_exports"],
        workspace_explicit_exports=values["workspace_explicit_exports"],
        touched_all_assignment=values["touched_all_assignment"],
        unresolved_all_contract=values["unresolved_all_contract"],
        partial_unresolved_all_exports=values["partial_unresolved_all_exports"],
        workspace_public_names=values["workspace_public_names"],
    )
    values.update(constructor_values)
    return PythonDetectionContext(file_diff=file_diff, **values)
