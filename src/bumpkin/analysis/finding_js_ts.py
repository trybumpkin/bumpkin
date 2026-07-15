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
    collector = _FindingCollector(build_finding=build_finding)
    for file_diff in file_diffs:
        if _is_js_ts_path(file_diff.path):
            _detect_file_exports(
                file_diff,
                collector=collector,
                normalize_type=normalize_type,
                is_optional_widening=is_optional_widening,
                is_requiredness_tightening=is_requiredness_tightening,
            )
    return collector.findings


@dataclass
class _FindingCollector:
    build_finding: BuildFinding
    findings: list[Finding]
    counter: int = 0

    def __init__(self, *, build_finding: BuildFinding) -> None:
        self.build_finding = build_finding
        self.findings = []

    def add(self, **kwargs: object) -> None:
        self.counter += 1
        self.findings.append(self.build_finding(counter=self.counter, **kwargs))


def _detect_file_exports(
    file_diff: finding_diff.FileDiff,
    *,
    collector: _FindingCollector,
    normalize_type: NormalizeType,
    is_optional_widening: OptionalWidening,
    is_requiredness_tightening: RequirednessTightening,
) -> None:
    start_count = len(collector.findings)
    removed_exports = _extract_export_names(file_diff.removed_lines)
    added_exports = _extract_export_names(file_diff.added_lines)
    removed_signatures = _extract_export_signatures(
        file_diff.removed_lines, normalize_type=normalize_type
    )
    added_signatures = _extract_export_signatures(
        file_diff.added_lines, normalize_type=normalize_type
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
        collector.add(
            severity="MAJOR",
            rule="export_symbol_renamed",
            confidence="high",
            title=f"Renamed exported symbol: {old_name} -> {new_name}",
            why="Renaming an exported symbol removes the old public API name and breaks existing imports.",
            path=file_diff.path,
            snippet=f"{old_name} -> {new_name}",
        )
    removed_only = [symbol for symbol in removed_only if symbol not in renamed_removed]
    added_only = [symbol for symbol in added_only if symbol not in renamed_added]
    _add_name_delta_findings(file_diff, collector, removed_only, added_only)
    shared_exports = sorted(removed_exports & added_exports)
    _add_signature_findings(
        file_diff,
        collector,
        shared_exports,
        removed_signatures,
        added_signatures,
        is_optional_widening=is_optional_widening,
        is_requiredness_tightening=is_requiredness_tightening,
    )
    if len(collector.findings) == start_count:
        _add_behavior_fallback(
            file_diff,
            collector,
            shared_exports,
            removed_signatures,
            added_signatures,
        )


def _add_name_delta_findings(
    file_diff: finding_diff.FileDiff,
    collector: _FindingCollector,
    removed_only: list[str],
    added_only: list[str],
) -> None:
    if removed_only:
        collector.add(
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
        )
    if added_only:
        collector.add(
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
        )


def _add_signature_findings(
    file_diff: finding_diff.FileDiff,
    collector: _FindingCollector,
    shared_exports: list[str],
    removed_signatures: Mapping[str, Sequence[JsTsFunctionSignature]],
    added_signatures: Mapping[str, Sequence[JsTsFunctionSignature]],
    *,
    is_optional_widening: OptionalWidening,
    is_requiredness_tightening: RequirednessTightening,
) -> None:
    for symbol in shared_exports:
        old_sigs = removed_signatures.get(symbol, [])
        new_sigs = added_signatures.get(symbol, [])
        if not old_sigs or not new_sigs:
            continue
        old_signature = old_sigs[0]
        new_signature = new_sigs[0]
        if (
            old_signature.params == new_signature.params
            and old_signature.return_type == new_signature.return_type
        ):
            continue
        if is_optional_widening(old_signature.params, new_signature.params):
            collector.add(
                severity="MINOR",
                rule="export_signature_optional_widening",
                confidence="medium",
                title=f"Backward-compatible signature widening: {symbol}",
                why="An exported function added only optional parameters, which is backward compatible for existing callers.",
                path=file_diff.path,
                snippet=new_signature.source,
            )
        elif is_requiredness_tightening(old_signature.params, new_signature.params):
            collector.add(
                severity="MAJOR",
                rule="export_signature_requiredness_tightening",
                confidence="high",
                title=f"Breaking signature tightening: {symbol}",
                why="The exported function signature became stricter, which can break callers.",
                path=file_diff.path,
                snippet=new_signature.source,
            )
        elif (
            old_signature.return_type
            and new_signature.return_type
            and old_signature.return_type != new_signature.return_type
        ):
            collector.add(
                severity="MAJOR",
                rule="export_return_type_changed",
                confidence="medium",
                title=f"Exported return type changed: {symbol}",
                why="Changing an exported return type can break downstream consumers expecting the previous contract.",
                path=file_diff.path,
                snippet=new_signature.source,
            )
        else:
            collector.add(
                severity="MAJOR",
                rule="export_signature_incompatible_change",
                confidence="medium",
                title=f"Incompatible exported signature change: {symbol}",
                why="The exported API signature changed in a way that is not clearly backward compatible.",
                path=file_diff.path,
                snippet=new_signature.source,
            )


def _add_behavior_fallback(
    file_diff: finding_diff.FileDiff,
    collector: _FindingCollector,
    shared_exports: list[str],
    removed_signatures: Mapping[str, Sequence[JsTsFunctionSignature]],
    added_signatures: Mapping[str, Sequence[JsTsFunctionSignature]],
) -> None:
    if shared_exports and file_diff.touched_export_markers:
        unchanged = all(
            removed_signatures.get(symbol)
            and added_signatures.get(symbol)
            and removed_signatures[symbol][0].params == added_signatures[symbol][0].params
            and removed_signatures[symbol][0].return_type == added_signatures[symbol][0].return_type
            for symbol in shared_exports
        )
        if unchanged:
            collector.add(
                severity="PATCH",
                rule="export_behavior_change_no_signature_delta",
                confidence="medium",
                title="Exported behavior changed without API signature change",
                why="The exported symbol remains present with the same signature, so this is treated as a patch-level behavior change.",
                path=file_diff.path,
                snippet=file_diff.added_lines[0] if file_diff.added_lines else "",
            )
            return
    if file_diff.touched_export_markers:
        collector.add(
            severity="MANUAL_REVIEW",
            rule="export_change_unclassified",
            confidence="low",
            title="Export change requires manual review",
            why="Export markers changed but deterministic rules could not infer a safe SemVer classification.",
            path=file_diff.path,
            snippet=file_diff.added_lines[0]
            if file_diff.added_lines
            else (file_diff.removed_lines[0] if file_diff.removed_lines else "export change"),
        )
