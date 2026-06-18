from __future__ import annotations

from collections.abc import Callable

from bumpkin.analysis import finding_diff, finding_types, finding_workspace

from . import (
    finding_python_detection_context,
    finding_python_signature_findings,
    finding_python_surface_findings,
)

_parse_diff_files = finding_diff.parse_diff_files
Finding = finding_types.Finding
WorkspaceLoader = finding_workspace.WorkspaceLoader
PYTHON_EXTENSIONS = finding_python_detection_context.PYTHON_EXTENSIONS


def run_python_api_detection(
    diff_text: str,
    *,
    workspace_loader: WorkspaceLoader | None,
    build_finding: Callable[..., Finding],
) -> list[Finding]:
    findings: list[Finding] = []
    counter = 0

    for file_diff in _parse_diff_files(diff_text):
        floor_raise = finding_python_detection_context.detect_python_packaging_floor_raise(file_diff)
        if floor_raise is not None:
            removed_floor, added_floor = floor_raise
            counter += 1
            findings.append(
                build_finding(
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
                                for marker in (
                                    "requires-python",
                                    "python_requires",
                                    "python =",
                                )
                            )
                        ),
                        file_diff.added_lines[0] if file_diff.added_lines else "",
                    ),
                    counter=counter,
                )
            )
            continue

        if not finding_python_detection_context.is_python_path(file_diff.path):
            continue

        context = finding_python_detection_context.build_python_detection_context(
            file_diff,
            workspace_loader=workspace_loader,
        )
        start_count = len(findings)
        counter = finding_python_surface_findings.append_python_surface_findings(
            findings,
            counter=counter,
            context=context,
            build_finding=build_finding,
        )
        counter = finding_python_signature_findings.append_python_signature_findings(
            findings,
            counter=counter,
            context=context,
            build_finding=build_finding,
        )
        if len(findings) == start_count:
            counter = finding_python_signature_findings.append_python_class_fallback_findings(
                findings,
                counter=counter,
                context=context,
                build_finding=build_finding,
            )

    return findings
