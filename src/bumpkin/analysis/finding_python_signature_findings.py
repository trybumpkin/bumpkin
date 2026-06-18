from __future__ import annotations

from collections.abc import Callable

from bumpkin.analysis import (
    finding_python_parameter_compat,
    finding_python_signatures,
    finding_types,
)

from .finding_python_detection_context import PythonDetectionContext

Finding = finding_types.Finding
_is_public_python_member_symbol = finding_python_signatures.is_public_python_member_symbol
_match_python_member_renames = finding_python_signatures.match_python_member_renames
_signature_key = finding_python_signatures.signature_key
_has_compatible_python_parameter_surface = (
    finding_python_parameter_compat.has_compatible_python_parameter_surface
)
_is_optional_widening = finding_python_parameter_compat.is_optional_widening
_is_requiredness_tightening = finding_python_parameter_compat.is_requiredness_tightening


def append_python_signature_findings(
    findings: list[Finding],
    *,
    counter: int,
    context: PythonDetectionContext,
    build_finding: Callable[..., Finding],
) -> int:
    removed_member_only = sorted(
        symbol
        for symbol in (set(context.removed_signatures) - set(context.added_signatures))
        if _is_public_python_member_symbol(
            symbol,
            public_exports=context.shared_public_exports,
            public_classes=context.workspace_public_classes,
        )
    )
    added_member_only = sorted(
        symbol
        for symbol in (set(context.added_signatures) - set(context.removed_signatures))
        if _is_public_python_member_symbol(
            symbol,
            public_exports=context.shared_public_exports,
            public_classes=context.workspace_public_classes,
        )
    )
    member_rename_pairs = _match_python_member_renames(
        removed_symbols=removed_member_only,
        added_symbols=added_member_only,
        removed_signatures=context.removed_signatures,
        added_signatures=context.added_signatures,
    )
    renamed_removed_members = {old_name for old_name, _ in member_rename_pairs}
    renamed_added_members = {new_name for _, new_name in member_rename_pairs}
    for old_name, new_name in member_rename_pairs:
        counter += 1
        findings.append(
            build_finding(
                severity="MAJOR",
                rule="export_symbol_renamed",
                confidence="high",
                title=f"Renamed public Python symbol: {old_name} -> {new_name}",
                why=(
                    "Renaming a public Python method removes the previous supported call path "
                    "for downstream users."
                ),
                path=context.file_diff.path,
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
            build_finding(
                severity="MAJOR",
                rule="export_symbol_removed",
                confidence="high",
                title=f"Removed public Python symbol(s): {', '.join(removed_member_only[:3])}",
                why="Removing public Python methods is a breaking change for downstream users.",
                path=context.file_diff.path,
                snippet=next(
                    (
                        line
                        for line in context.file_diff.removed_lines
                        if any(symbol.rsplit(".", 1)[-1] in line for symbol in removed_member_only)
                    ),
                    context.file_diff.removed_lines[0] if context.file_diff.removed_lines else "",
                ),
                counter=counter,
            )
        )
    if added_member_only:
        counter += 1
        findings.append(
            build_finding(
                severity="MINOR",
                rule="export_symbol_added",
                confidence="high",
                title=f"Added public Python symbol(s): {', '.join(added_member_only[:3])}",
                why="Adding public Python methods expands the supported API surface.",
                path=context.file_diff.path,
                snippet=next(
                    (
                        line
                        for line in context.file_diff.added_lines
                        if any(symbol.rsplit(".", 1)[-1] in line for symbol in added_member_only)
                    ),
                    context.file_diff.added_lines[0] if context.file_diff.added_lines else "",
                ),
                counter=counter,
            )
        )
    shared_symbols = sorted(
        symbol
        for symbol in (set(context.removed_signatures) & set(context.added_signatures))
        if _is_public_python_member_symbol(
            symbol,
            public_exports=context.shared_public_exports,
            public_classes=context.workspace_public_classes,
        )
    )
    for symbol in shared_symbols:
        old_sigs = context.removed_signatures.get(symbol, [])
        new_sigs = context.added_signatures.get(symbol, [])
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
                    build_finding(
                        severity="MAJOR",
                        rule="export_overload_removed",
                        confidence="high",
                        title=f"Removed public Python overload(s): {symbol}",
                        why=(
                            "Removing a public overload narrows the supported call surface for "
                            "downstream users."
                        ),
                        path=context.file_diff.path,
                        snippet=old_sigs[0].source,
                        counter=counter,
                    )
                )
            elif added_overloads and not removed_overloads:
                findings.append(
                    build_finding(
                        severity="MINOR",
                        rule="export_overload_added",
                        confidence="medium",
                        title=f"Added public Python overload(s): {symbol}",
                        why=(
                            "Adding a public overload expands the supported call surface "
                            "without removing existing ones."
                        ),
                        path=context.file_diff.path,
                        snippet=new_sigs[0].source,
                        counter=counter,
                    )
                )
            else:
                findings.append(
                    build_finding(
                        severity="MAJOR",
                        rule="export_overload_changed",
                        confidence="high",
                        title=f"Changed public Python overload set: {symbol}",
                        why=(
                            "Changing the supported overload set can remove previously valid call "
                            "patterns for downstream users."
                        ),
                        path=context.file_diff.path,
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
                build_finding(
                    severity="MAJOR",
                    rule="export_async_contract_changed",
                    confidence="high",
                    title=f"Public Python async contract changed: {symbol}",
                    why=(
                        "Switching between async and sync changes how callers must invoke the "
                        "public Python callable."
                    ),
                    path=context.file_diff.path,
                    snippet=new_sigs[0].source,
                    counter=counter,
                )
            )
            continue

        if old_method_kind != new_method_kind:
            counter += 1
            findings.append(
                build_finding(
                    severity="MAJOR",
                    rule="export_method_binding_changed",
                    confidence="high",
                    title=f"Public Python method binding changed: {symbol}",
                    why=(
                        "Changing whether a public method is bound as an instance, class, static, "
                        "or property-style accessor changes how downstream callers must access it."
                    ),
                    path=context.file_diff.path,
                    snippet=new_sigs[0].source,
                    counter=counter,
                )
            )
            continue

        if _is_optional_widening(old_params, new_params):
            counter += 1
            findings.append(
                build_finding(
                    severity="MINOR",
                    rule="export_signature_optional_widening",
                    confidence="medium",
                    title=f"Backward-compatible Python signature widening: {symbol}",
                    why=(
                        "The public Python callable added only optional parameters, which should "
                        "remain backward compatible."
                    ),
                    path=context.file_diff.path,
                    snippet=new_sigs[0].source,
                    counter=counter,
                )
            )
            continue

        if _is_requiredness_tightening(old_params, new_params):
            counter += 1
            findings.append(
                build_finding(
                    severity="MAJOR",
                    rule="export_signature_requiredness_tightening",
                    confidence="high",
                    title=f"Breaking Python signature tightening: {symbol}",
                    why=(
                        "The public Python callable became stricter by adding required input or "
                        "tightening existing parameters."
                    ),
                    path=context.file_diff.path,
                    snippet=new_sigs[0].source,
                    counter=counter,
                )
            )
            continue

        if old_return and new_return and old_return != new_return:
            counter += 1
            findings.append(
                build_finding(
                    severity="MAJOR",
                    rule="export_return_type_changed",
                    confidence="medium",
                    title=f"Public Python return type changed: {symbol}",
                    why=(
                        "Changing the declared return contract of a public Python callable can "
                        "break consumers and typing expectations."
                    ),
                    path=context.file_diff.path,
                    snippet=new_sigs[0].source,
                    counter=counter,
                )
            )
            continue

        if _has_compatible_python_parameter_surface(old_params, new_params):
            continue

        counter += 1
        findings.append(
            build_finding(
                severity="MAJOR",
                rule="export_signature_incompatible_change",
                confidence="medium",
                title=f"Incompatible public Python signature change: {symbol}",
                why=(
                    "The public Python callable changed in a way that is not clearly backward "
                    "compatible."
                ),
                path=context.file_diff.path,
                snippet=new_sigs[0].source,
                counter=counter,
            )
        )

    if context.unreexported_local_public_exports:
        unresolved_local_symbols = sorted(
            symbol
            for symbol in (set(context.removed_signatures) & set(context.added_signatures))
            if (
                symbol in context.unreexported_local_public_exports
                or (
                    symbol.endswith(".__init__")
                    and symbol.rsplit(".", 1)[0] in context.unreexported_local_public_exports
                )
            )
            and set(map(_signature_key, context.removed_signatures.get(symbol, [])))
            != set(map(_signature_key, context.added_signatures.get(symbol, [])))
        )
        if unresolved_local_symbols:
            counter += 1
            findings.append(
                build_finding(
                    severity="MANUAL_REVIEW",
                    rule="python_api_module_local_surface_changed",
                    confidence="low",
                    title=(
                        "Changed local api.py public-surface candidate requires manual review: "
                        f"{', '.join(unresolved_local_symbols[:3])}"
                    ),
                    why=(
                        "This api.py module changed a local top-level symbol that is not "
                        "re-exported from the package root. Bumpkin cannot deterministically tell "
                        "whether it is part of the public submodule API or an internal helper, so "
                        "the change should be reviewed manually."
                    ),
                    path=context.file_diff.path,
                    snippet=next(
                        (
                            line
                            for line in (
                                *context.file_diff.added_lines,
                                *context.file_diff.removed_lines,
                            )
                            if any(
                                symbol.rsplit(".", 1)[-1] in line
                                for symbol in unresolved_local_symbols
                            )
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

    if context.nested_constructor_change:
        counter += 1
        findings.append(
            build_finding(
                severity="MANUAL_REVIEW",
                rule="python_nested_constructor_changed",
                confidence="low",
                title="Changed nested Python constructor requires manual review",
                why=(
                    "A nested Python class constructor changed, and Bumpkin does not "
                    "deterministically classify nested-class API compatibility yet."
                ),
                path=context.file_diff.path,
                snippet=next(
                    (
                        line
                        for line in (
                            *context.file_diff.added_lines,
                            *context.file_diff.removed_lines,
                        )
                        if "__init__" in line
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

    if context.ambiguous_constructor_change or context.unresolved_constructor_change:
        counter += 1
        findings.append(
            build_finding(
                severity="MANUAL_REVIEW",
                rule="python_constructor_ambiguous",
                confidence="low",
                title="Changed Python constructor requires manual review",
                why=(
                    "A public __init__ changed, but Bumpkin could not confidently resolve it to a "
                    "single class from the available analysis context."
                ),
                path=context.file_diff.path,
                snippet=next(
                    (
                        line
                        for line in (
                            *context.file_diff.added_lines,
                            *context.file_diff.removed_lines,
                        )
                        if "__init__" in line
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


def append_python_class_fallback_findings(
    findings: list[Finding],
    *,
    counter: int,
    context: PythonDetectionContext,
    build_finding: Callable[..., Finding],
) -> int:
    removed_only_classes = sorted(context.removed_classes - context.added_classes)
    added_only_classes = sorted(context.added_classes - context.removed_classes)
    if removed_only_classes:
        counter += 1
        findings.append(
            build_finding(
                severity="MAJOR",
                rule="export_symbol_removed",
                confidence="high",
                title=f"Removed public Python class(es): {', '.join(removed_only_classes[:3])}",
                why="Removing a public Python class is a breaking API change.",
                path=context.file_diff.path,
                snippet=next(
                    (
                        line
                        for line in context.file_diff.removed_lines
                        if any(symbol in line for symbol in removed_only_classes)
                    ),
                    context.file_diff.removed_lines[0] if context.file_diff.removed_lines else "",
                ),
                counter=counter,
            )
        )
    elif added_only_classes:
        counter += 1
        findings.append(
            build_finding(
                severity="MINOR",
                rule="export_symbol_added",
                confidence="high",
                title=f"Added public Python class(es): {', '.join(added_only_classes[:3])}",
                why="Adding a public Python class expands the available API surface.",
                path=context.file_diff.path,
                snippet=next(
                    (
                        line
                        for line in context.file_diff.added_lines
                        if any(symbol in line for symbol in added_only_classes)
                    ),
                    context.file_diff.added_lines[0] if context.file_diff.added_lines else "",
                ),
                counter=counter,
            )
        )
    return counter
