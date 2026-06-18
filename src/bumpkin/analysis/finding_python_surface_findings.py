from __future__ import annotations

from collections.abc import Callable

from bumpkin.analysis import finding_js_ts, finding_python_surface, finding_types

from .finding_python_detection_context import PythonDetectionContext

_match_export_renames = finding_js_ts.match_export_renames
_is_python_api_surface = finding_python_surface.is_python_api_surface
Finding = finding_types.Finding


def append_python_surface_findings(
    findings: list[Finding],
    *,
    counter: int,
    context: PythonDetectionContext,
    build_finding: Callable[..., Finding],
) -> int:
    if context.unresolved_all_contract and (
        context.unresolved_candidate_names
        or context.touched_all_assignment
        or context.touched_meaningful_code
    ):
        counter += 1
        findings.append(
            build_finding(
                severity="MANUAL_REVIEW",
                rule="python_all_unresolved",
                confidence="low",
                title="Unable to resolve explicit Python __all__ contract",
                why=(
                    "This module declares __all__ using a dynamic or unsupported expression, so "
                    "Bumpkin cannot deterministically confirm whether the changed symbol is part "
                    "of the public surface."
                ),
                path=context.file_diff.path,
                snippet=next(
                    (
                        line
                        for line in (
                            *context.file_diff.added_lines,
                            *context.file_diff.removed_lines,
                        )
                        if "__all__" in line
                    ),
                    context.file_diff.added_lines[0]
                    if context.file_diff.added_lines
                    else (
                        context.file_diff.removed_lines[0]
                        if context.file_diff.removed_lines
                        else ""
                    ),
                ),
                counter=counter,
            )
        )

    if context.removed_star_reexports != context.added_star_reexports and (
        context.removed_star_reexports or context.added_star_reexports
    ):
        counter += 1
        findings.append(
            build_finding(
                severity="MANUAL_REVIEW",
                rule="python_star_reexport_changed",
                confidence="low",
                title="Changed Python star re-export requires manual review",
                why=(
                    "A Python facade changed a star re-export, so Bumpkin cannot "
                    "deterministically enumerate which public symbols were added or removed."
                ),
                path=context.file_diff.path,
                snippet=next(
                    (
                        line
                        for line in (
                            *context.file_diff.added_lines,
                            *context.file_diff.removed_lines,
                        )
                        if "import *" in line
                    ),
                    context.file_diff.added_lines[0]
                    if context.file_diff.added_lines
                    else (
                        context.file_diff.removed_lines[0]
                        if context.file_diff.removed_lines
                        else ""
                    ),
                ),
                counter=counter,
            )
        )

    removed_only = sorted(context.removed_exports - context.added_exports)
    added_only = sorted(context.added_exports - context.removed_exports)
    rename_pairs = _match_export_renames(
        removed_only=removed_only,
        added_only=added_only,
        removed_signatures=context.removed_signatures,
        added_signatures=context.added_signatures,
    )
    renamed_removed = {old_name for old_name, _ in rename_pairs}
    renamed_added = {new_name for _, new_name in rename_pairs}

    for old_name, new_name in rename_pairs:
        counter += 1
        findings.append(
            build_finding(
                severity="MAJOR",
                rule="export_symbol_renamed",
                confidence="high",
                title=f"Renamed public Python symbol: {old_name} -> {new_name}",
                why=(
                    "Renaming a public Python symbol removes the previous import path for "
                    "downstream users."
                ),
                path=context.file_diff.path,
                snippet=f"{old_name} -> {new_name}",
                counter=counter,
            )
        )

    removed_only = [symbol for symbol in removed_only if symbol not in renamed_removed]
    if removed_only:
        counter += 1
        findings.append(
            build_finding(
                severity="MAJOR",
                rule="export_symbol_removed",
                confidence="high",
                title=f"Removed public Python symbol(s): {', '.join(removed_only[:3])}",
                why="Removing public Python API symbols is a breaking change for importers.",
                path=context.file_diff.path,
                snippet=next(
                    (
                        line
                        for line in context.file_diff.removed_lines
                        if any(symbol in line for symbol in removed_only)
                    ),
                    context.file_diff.removed_lines[0] if context.file_diff.removed_lines else "",
                ),
                counter=counter,
            )
        )

    added_only = [symbol for symbol in added_only if symbol not in renamed_added]
    if added_only:
        counter += 1
        findings.append(
            build_finding(
                severity="MINOR",
                rule="export_symbol_added",
                confidence="high",
                title=f"Added public Python symbol(s): {', '.join(added_only[:3])}",
                why="Adding public Python API symbols expands the supported surface area.",
                path=context.file_diff.path,
                snippet=next(
                    (
                        line
                        for line in context.file_diff.added_lines
                        if any(symbol in line for symbol in added_only)
                    ),
                    context.file_diff.added_lines[0] if context.file_diff.added_lines else "",
                ),
                counter=counter,
            )
        )

    shared_import_binding_symbols = sorted(
        symbol
        for symbol in (set(context.removed_import_bindings) & set(context.added_import_bindings))
        if symbol in context.shared_public_exports
        and context.removed_import_bindings[symbol] != context.added_import_bindings[symbol]
    )
    for symbol in shared_import_binding_symbols:
        counter += 1
        findings.append(
            build_finding(
                severity="MAJOR",
                rule="export_reexport_target_changed",
                confidence="high",
                title=f"Changed public Python re-export target: {symbol}",
                why=(
                    "The public Python symbol still has the same exported name, but it now "
                    "resolves to a different imported target for downstream users."
                ),
                path=context.file_diff.path,
                snippet=next(
                    (
                        line
                        for line in (
                            *context.file_diff.added_lines,
                            *context.file_diff.removed_lines,
                        )
                        if symbol in line
                    ),
                    context.file_diff.added_lines[0]
                    if context.file_diff.added_lines
                    else (
                        context.file_diff.removed_lines[0]
                        if context.file_diff.removed_lines
                        else ""
                    ),
                ),
                counter=counter,
            )
        )

    removed_bound_public_names = context.removed_local_public_names | set(
        context.removed_import_bindings
    )
    added_bound_public_names = context.added_local_public_names | set(context.added_import_bindings)
    removed_explicit_binding_symbols = sorted(
        symbol
        for symbol in context.shared_public_exports
        if symbol in removed_bound_public_names and symbol not in added_bound_public_names
    )
    for symbol in removed_explicit_binding_symbols:
        counter += 1
        findings.append(
            build_finding(
                severity="MAJOR",
                rule="export_symbol_removed",
                confidence="high",
                title=f"Removed public Python symbol(s): {symbol}",
                why=(
                    "An explicitly exported Python symbol no longer resolves to a matching "
                    "public binding for downstream importers."
                ),
                path=context.file_diff.path,
                snippet=next(
                    (
                        line
                        for line in (
                            *context.file_diff.added_lines,
                            *context.file_diff.removed_lines,
                        )
                        if symbol in line
                    ),
                    context.file_diff.added_lines[0]
                    if context.file_diff.added_lines
                    else (
                        context.file_diff.removed_lines[0]
                        if context.file_diff.removed_lines
                        else ""
                    ),
                ),
                counter=counter,
            )
        )

    unresolved_api_import_binding_symbols = sorted(
        symbol
        for symbol in (set(context.removed_import_bindings) & set(context.added_import_bindings))
        if _is_python_api_surface(context.file_diff.path)
        and symbol not in context.shared_public_exports
        and context.removed_import_bindings[symbol] != context.added_import_bindings[symbol]
    )
    if unresolved_api_import_binding_symbols:
        counter += 1
        findings.append(
            build_finding(
                severity="MANUAL_REVIEW",
                rule="python_api_module_import_binding_changed",
                confidence="low",
                title=(
                    "Changed api.py import-surface candidate requires manual review: "
                    f"{', '.join(unresolved_api_import_binding_symbols[:3])}"
                ),
                why=(
                    "This api.py module changed an imported symbol target without stronger "
                    "export evidence. Bumpkin cannot deterministically tell whether it is part of "
                    "the public submodule API or an internal wiring detail."
                ),
                path=context.file_diff.path,
                snippet=next(
                    (
                        line
                        for line in (
                            *context.file_diff.added_lines,
                            *context.file_diff.removed_lines,
                        )
                        if any(symbol in line for symbol in unresolved_api_import_binding_symbols)
                    ),
                    context.file_diff.added_lines[0]
                    if context.file_diff.added_lines
                    else (
                        context.file_diff.removed_lines[0]
                        if context.file_diff.removed_lines
                        else ""
                    ),
                ),
                counter=counter,
            )
        )

    stable_local_api_surface_names = {
        name
        for name in (context.removed_local_public_names & context.added_local_public_names)
        if name.lower() not in {"helper", "helpers", "util", "utils"}
    }
    explicit_api_import_alias_change = _extract_explicit_api_import_alias_change(context)
    unresolved_api_import_surface_symbols = sorted(
        symbol
        for symbol in (context.removed_import_public_names ^ context.added_import_public_names)
        if _is_python_api_surface(context.file_diff.path)
        and context.workspace_explicit_exports is None
        and not context.removed_has_explicit_all
        and not context.added_has_explicit_all
        and (not stable_local_api_surface_names or explicit_api_import_alias_change)
        and symbol not in context.removed_exports
        and symbol not in context.added_exports
    )
    if unresolved_api_import_surface_symbols:
        counter += 1
        findings.append(
            build_finding(
                severity="MANUAL_REVIEW",
                rule="python_api_module_import_surface_changed",
                confidence="low",
                title=(
                    "Changed api.py import-surface candidate requires manual review: "
                    f"{', '.join(unresolved_api_import_surface_symbols[:3])}"
                ),
                why=(
                    "This api.py module changed imported top-level symbols without stronger "
                    "export evidence. Bumpkin cannot deterministically tell whether those imports "
                    "are part of the public submodule API or internal wiring."
                ),
                path=context.file_diff.path,
                snippet=next(
                    (
                        line
                        for line in (
                            *context.file_diff.added_lines,
                            *context.file_diff.removed_lines,
                        )
                        if any(symbol in line for symbol in unresolved_api_import_surface_symbols)
                    ),
                    context.file_diff.added_lines[0]
                    if context.file_diff.added_lines
                    else (
                        context.file_diff.removed_lines[0]
                        if context.file_diff.removed_lines
                        else ""
                    ),
                ),
                counter=counter,
            )
        )

    return counter


def _extract_explicit_api_import_alias_change(context: PythonDetectionContext) -> bool:
    from bumpkin.analysis.finding_python_surface import has_python_explicit_public_import_alias

    return has_python_explicit_public_import_alias(
        context.removed_version_lines,
        path=context.file_diff.path,
    ) or has_python_explicit_public_import_alias(
        context.added_version_lines,
        path=context.file_diff.path,
    )
