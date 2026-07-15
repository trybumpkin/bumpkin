from __future__ import annotations

from bumpkin.analysis.diffing import DiffResult
from bumpkin.analysis.findings import build_filesystem_workspace_loader
from bumpkin.orchestrator.core_assembly import CoreAnalysisResult
from bumpkin.orchestrator.core_compat import resolve_compat
from bumpkin.orchestrator.core_pipeline import analyze_diff_core

__all__ = ["CoreAnalysisResult", "analyze_diff_core"]


def _workspace_loader_for_diff_result(diff_result: DiffResult):  # pyright: ignore[reportUnusedFunction]
    repo_root = (diff_result.repo_root or "").strip()
    if not repo_root:
        return None
    return build_filesystem_workspace_loader(repo_root)


def __getattr__(name: str):
    return resolve_compat(name)
