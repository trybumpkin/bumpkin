from __future__ import annotations

import re
from dataclasses import dataclass

DIFF_GIT_HEADER = re.compile(r"^diff --git a/(.+?) b/(.+)$")


@dataclass
class FileDiff:
    path: str
    removed_lines: list[str]
    added_lines: list[str]
    context_lines: list[str]
    ordered_lines: list[tuple[str, str]]
    touched_export_markers: bool


def parse_diff_files(diff_text: str) -> list[FileDiff]:
    file_diffs: list[FileDiff] = []
    current: FileDiff | None = None
    saw_header = False

    for raw in diff_text.splitlines():
        header = DIFF_GIT_HEADER.match(raw.strip())
        if header:
            saw_header = True
            if current is not None:
                file_diffs.append(current)
            current = FileDiff(
                path=header.group(2),
                removed_lines=[],
                added_lines=[],
                context_lines=[],
                ordered_lines=[],
                touched_export_markers=False,
            )
            continue

        if current is None:
            continue
        if raw.startswith(("---", "+++", "@@", "index ")):
            continue
        if raw.startswith("-"):
            line = raw[1:].rstrip()
            if line.strip():
                current.removed_lines.append(line)
                current.ordered_lines.append(("-", line))
                if "export " in line:
                    current.touched_export_markers = True
        elif raw.startswith("+"):
            line = raw[1:].rstrip()
            if line.strip():
                current.added_lines.append(line)
                current.ordered_lines.append(("+", line))
                if "export " in line:
                    current.touched_export_markers = True
        elif raw.startswith(" "):
            line = raw[1:].rstrip()
            if line.strip():
                current.context_lines.append(line)
                current.ordered_lines.append((" ", line))

    if current is not None:
        file_diffs.append(current)

    if saw_header:
        return file_diffs

    # Fallback for synthetic diffs without git headers.
    removed: list[str] = []
    added: list[str] = []
    touched_export = False
    for raw in diff_text.splitlines():
        if raw.startswith(("---", "+++", "@@", "index ", "diff --git ")):
            continue
        if raw.startswith("-"):
            line = raw[1:].rstrip()
            if line.strip():
                removed.append(line)
                if "export " in line:
                    touched_export = True
        elif raw.startswith("+"):
            line = raw[1:].rstrip()
            if line.strip():
                added.append(line)
                if "export " in line:
                    touched_export = True
    if not removed and not added:
        return []
    return [
        FileDiff(
            path="<unknown>.ts",
            removed_lines=removed,
            added_lines=added,
            context_lines=[],
            ordered_lines=[*[("-", line) for line in removed], *[("+", line) for line in added]],
            touched_export_markers=touched_export,
        )
    ]
