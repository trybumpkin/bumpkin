import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from bumpkin.analysis import finding_diff
from bumpkin.analysis.finding_types import Finding

EXPORT_DECL_PATTERNS = [
    re.compile(r"\bexport\s+(?:declare\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"\bexport\s+(?:declare\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"\bexport\s+(?:declare\s+)?(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"\bexport\s+(?:declare\s+)?(?:interface|type|enum)\s+([A-Za-z_][A-Za-z0-9_]*)"),
]

EXPORT_FUNCTION_SIGNATURE_PATTERNS = [
    re.compile(
        r"\bexport\s+(?:declare\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*"
        r"\(([^)]*)\)\s*(?::\s*([^{=]+?))?\s*(?:\{|$)"
    ),
    re.compile(
        r"\bexport\s+(?:declare\s+)?(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
        r"(?:async\s*)?\(([^)]*)\)\s*(?::\s*([^=]+?))?\s*=>"
    ),
]


class SignatureLike(Protocol):
    params: str
    return_type: str | None
    is_async: bool
    method_kind: str | None


@dataclass(frozen=True)
class JsTsFunctionSignature:
    name: str
    params: str
    return_type: str | None
    is_async: bool
    source: str
    method_kind: str | None = None


BuildFinding = Callable[..., Finding]
NormalizeType = Callable[[str | None], str | None]
OptionalWidening = Callable[[str, str], bool]
RequirednessTightening = Callable[[str, str], bool]


def _signatures_equivalent(left: SignatureLike, right: SignatureLike) -> bool:
    return (
        left.params == right.params
        and left.return_type == right.return_type
        and left.is_async == right.is_async
        and left.method_kind == right.method_kind
    )


def match_export_renames(
    *,
    removed_only: list[str],
    added_only: list[str],
    removed_signatures: Mapping[str, Sequence[object]],
    added_signatures: Mapping[str, Sequence[object]],
) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    used_added: set[str] = set()
    for old_name in removed_only:
        old_sigs = removed_signatures.get(old_name, [])
        if not old_sigs:
            continue
        for new_name in added_only:
            if new_name in used_added:
                continue
            new_sigs = added_signatures.get(new_name, [])
            if not new_sigs:
                continue
            equivalent = any(
                _signatures_equivalent(
                    cast("SignatureLike", old_sig), cast("SignatureLike", new_sig)
                )
                for old_sig in old_sigs
                for new_sig in new_sigs
            )
            if not equivalent:
                continue
            pairs.append((old_name, new_name))
            used_added.add(new_name)
            break
    return pairs


def _is_js_ts_path(path: str) -> bool:
    normalized = path.strip().lower()
    return normalized.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"))


def _extract_export_names(lines: list[str]) -> set[str]:
    exports: set[str] = set()
    for line in lines:
        for pattern in EXPORT_DECL_PATTERNS:
            match = pattern.search(line)
            if match:
                exports.add(match.group(1))
        if "export default" in line:
            exports.add("__default__")
        brace_export_match = re.search(r"\bexport\s*{\s*([^}]+)\s*}", line)
        if brace_export_match:
            members = [member.strip() for member in brace_export_match.group(1).split(",")]
            for member in members:
                if not member:
                    continue
                if " as " in member:
                    exports.add(member.split(" as ", 1)[1].strip())
                else:
                    exports.add(member)
    return exports


def _extract_export_signatures(
    lines: list[str],
    *,
    normalize_type: NormalizeType,
) -> dict[str, list[JsTsFunctionSignature]]:
    signatures: dict[str, list[JsTsFunctionSignature]] = {}
    for line in lines:
        for pattern in EXPORT_FUNCTION_SIGNATURE_PATTERNS:
            for match in pattern.finditer(line):
                signature = JsTsFunctionSignature(
                    name=match.group(1),
                    params=re.sub(r"\s+", "", match.group(2)),
                    return_type=normalize_type(match.group(3)),
                    is_async=False,
                    source=line,
                )
                signatures.setdefault(signature.name, []).append(signature)
    return signatures


def run_js_ts_export_detection(
    diff_text: str,
    *,
    build_finding: BuildFinding,
    normalize_type: NormalizeType,
    is_optional_widening: OptionalWidening,
    is_requiredness_tightening: RequirednessTightening,
) -> list[Finding]:
    file_diffs = finding_diff.parse_diff_files(diff_text)
    findings: list[Finding] = []
    counter = 0

    for file_diff in file_diffs:
        if not _is_js_ts_path(file_diff.path):
            continue

        start_count = len(findings)
        removed_exports = _extract_export_names(file_diff.removed_lines)
        added_exports = _extract_export_names(file_diff.added_lines)
        removed_signatures = _extract_export_signatures(
            file_diff.removed_lines,
            normalize_type=normalize_type,
        )
        added_signatures = _extract_export_signatures(
            file_diff.added_lines,
            normalize_type=normalize_type,
        )

        removed_only = sorted(removed_exports - added_exports)
        added_only = sorted(added_exports - removed_exports)
        rename_pairs = match_export_renames(
            removed_only=removed_only,
            added_only=added_only,
            removed_signatures=removed_signatures,
            added_signatures=added_signatures,
        )
        renamed_removed = {old_name for old_name, _ in rename_pairs}
        renamed_added = {new_name for _, new_name in rename_pairs}

        for old_name, new_name in rename_pairs:
            counter += 1
            evidence = f"{old_name} -> {new_name}"
            findings.append(
                build_finding(
                    severity="MAJOR",
                    rule="export_symbol_renamed",
                    confidence="high",
                    title=f"Renamed exported symbol: {old_name} -> {new_name}",
                    why=(
                        "Renaming an exported symbol removes the old public API name and "
                        "breaks existing imports."
                    ),
                    path=file_diff.path,
                    snippet=evidence,
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
                    title=f"Removed exported symbol(s): {', '.join(removed_only[:3])}",
                    why="Removing exported API symbols is a breaking public API change.",
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
                build_finding(
                    severity="MINOR",
                    rule="export_symbol_added",
                    confidence="high",
                    title=f"Added exported symbol(s): {', '.join(added_only[:3])}",
                    why="Adding exported API symbols is a backward-compatible API expansion.",
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

        shared_exports = sorted(removed_exports & added_exports)

        for symbol in shared_exports:
            old_sigs = removed_signatures.get(symbol, [])
            new_sigs = added_signatures.get(symbol, [])
            if not old_sigs or not new_sigs:
                continue

            old_params = old_sigs[0].params
            new_params = new_sigs[0].params
            old_return = old_sigs[0].return_type
            new_return = new_sigs[0].return_type

            if old_params == new_params and old_return == new_return:
                continue

            if is_optional_widening(old_params, new_params):
                counter += 1
                findings.append(
                    build_finding(
                        severity="MINOR",
                        rule="export_signature_optional_widening",
                        confidence="medium",
                        title=f"Backward-compatible signature widening: {symbol}",
                        why=(
                            "An exported function added only optional parameters, which is "
                            "backward compatible for existing callers."
                        ),
                        path=file_diff.path,
                        snippet=new_sigs[0].source,
                        counter=counter,
                    )
                )
                continue

            if is_requiredness_tightening(old_params, new_params):
                counter += 1
                findings.append(
                    build_finding(
                        severity="MAJOR",
                        rule="export_signature_requiredness_tightening",
                        confidence="high",
                        title=f"Breaking signature tightening: {symbol}",
                        why=(
                            "The exported function signature became stricter "
                            "(removed/required parameter changes), which can break callers."
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
                    build_finding(
                        severity="MAJOR",
                        rule="export_return_type_changed",
                        confidence="medium",
                        title=f"Exported return type changed: {symbol}",
                        why=(
                            "Changing an exported return type can break downstream consumers "
                            "expecting the previous contract."
                        ),
                        path=file_diff.path,
                        snippet=new_sigs[0].source,
                        counter=counter,
                    )
                )
                continue

            counter += 1
            findings.append(
                build_finding(
                    severity="MAJOR",
                    rule="export_signature_incompatible_change",
                    confidence="medium",
                    title=f"Incompatible exported signature change: {symbol}",
                    why=(
                        "The exported API signature changed in a way that is not clearly "
                        "backward compatible."
                    ),
                    path=file_diff.path,
                    snippet=new_sigs[0].source,
                    counter=counter,
                )
            )

        if len(findings) == start_count and file_diff.touched_export_markers and shared_exports:
            unchanged_shared_signatures = True
            for symbol in shared_exports:
                old_sigs = removed_signatures.get(symbol, [])
                new_sigs = added_signatures.get(symbol, [])
                if not old_sigs or not new_sigs:
                    unchanged_shared_signatures = False
                    break
                if old_sigs[0].params != new_sigs[0].params:
                    unchanged_shared_signatures = False
                    break
                if old_sigs[0].return_type != new_sigs[0].return_type:
                    unchanged_shared_signatures = False
                    break
            if unchanged_shared_signatures:
                counter += 1
                findings.append(
                    build_finding(
                        severity="PATCH",
                        rule="export_behavior_change_no_signature_delta",
                        confidence="medium",
                        title="Exported behavior changed without API signature change",
                        why=(
                            "The exported symbol remains present with the same signature, "
                            "so this is treated as a patch-level behavior change."
                        ),
                        path=file_diff.path,
                        snippet=file_diff.added_lines[0] if file_diff.added_lines else "",
                        counter=counter,
                    )
                )

        if len(findings) == start_count and file_diff.touched_export_markers:
            counter += 1
            snippet = (
                file_diff.added_lines[0]
                if file_diff.added_lines
                else (file_diff.removed_lines[0] if file_diff.removed_lines else "export change")
            )
            findings.append(
                build_finding(
                    severity="MANUAL_REVIEW",
                    rule="export_change_unclassified",
                    confidence="low",
                    title="Export change requires manual review",
                    why=(
                        "Export markers changed but deterministic rules could not infer a "
                        "safe SemVer classification."
                    ),
                    path=file_diff.path,
                    snippet=snippet,
                    counter=counter,
                )
            )

    return findings
