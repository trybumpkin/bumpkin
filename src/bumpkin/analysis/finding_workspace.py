from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

PYTHON_SOURCE_ROOT_NAMES = {
    "src",
    "python",
    "lib",
    "package",
    "packages",
    "app",
    "apps",
    "service",
    "services",
    "backend",
    "backends",
}

WorkspaceLoader = Callable[[str], list[str] | None]


def build_filesystem_workspace_loader(
    base_dir: str | Path | None = None,
) -> WorkspaceLoader:
    base_path = (Path(base_dir) if base_dir is not None else Path.cwd()).resolve(strict=False)

    def _load(path: str) -> list[str] | None:
        candidate = Path(path)
        resolved = (
            candidate.resolve(strict=False)
            if candidate.is_absolute()
            else (base_path / candidate).resolve(strict=False)
        )
        try:
            resolved.relative_to(base_path)
        except ValueError:
            return None
        try:
            return resolved.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return None

    return _load


def read_workspace_python_lines(
    path: str,
    *,
    workspace_loader: WorkspaceLoader | None,
) -> list[str] | None:
    if workspace_loader is None:
        return None
    return workspace_loader(path)


def python_package_root(path: str) -> str | None:
    normalized = path.strip().replace("\\", "/").strip("/")
    if not normalized:
        return None
    parts = normalized.split("/")
    if len(parts) < 2:
        return None
    package_parts = parts[:-1]
    if parts[0] in PYTHON_SOURCE_ROOT_NAMES and len(parts) >= 3:
        package_parts = parts[1:-1]
    if not package_parts:
        return None
    package_root = ".".join(package_parts)
    return package_root or None


def python_module_candidates(path: str) -> set[str]:
    normalized = path.strip().replace("\\", "/").strip("/")
    if not normalized:
        return set()
    parts = normalized.split("/")
    if not parts:
        return set()
    module_parts = [*parts[:-1], Path(parts[-1]).stem]
    candidates = {".".join(module_parts)}
    if module_parts and module_parts[0] in PYTHON_SOURCE_ROOT_NAMES and len(module_parts) >= 2:
        candidates.add(".".join(module_parts[1:]))
    return {candidate for candidate in candidates if candidate}


def python_relative_module_from_ancestor(path: Path, ancestor_dir: Path) -> str | None:
    try:
        relative = path.relative_to(ancestor_dir)
    except ValueError:
        return None
    parts = relative.parts
    if not parts:
        return None
    module_parts = [*parts[:-1], Path(parts[-1]).stem]
    return ".".join(part for part in module_parts if part) or None
