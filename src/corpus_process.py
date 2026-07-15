from __future__ import annotations

import subprocess
from pathlib import Path


def run_command(args: list[str], *, stdin: str | None = None) -> str:
    proc = subprocess.run(
        args,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(args)}\n"
            f"stdout:\n{proc.stdout.strip()}\n"
            f"stderr:\n{proc.stderr.strip()}"
        )
    return proc.stdout


def run_git(repo: Path, args: list[str], *, stdin: str | None = None) -> str:
    return run_command(["git", "-C", str(repo), *args], stdin=stdin)


def run_gh(args: list[str]) -> str:
    return run_command(["gh", *args])
