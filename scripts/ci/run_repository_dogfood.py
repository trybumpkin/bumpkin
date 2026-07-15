from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from json import JSONDecodeError
from pathlib import Path
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Bumpkin against another repository worktree.")
    parser.add_argument("--repository", required=True, help="Repository worktree to analyze.")
    parser.add_argument("--from-ref", default="HEAD~1", help="Base git ref.")
    parser.add_argument("--to-ref", default="HEAD", help="Target git ref.")
    parser.add_argument("--mode", default="stub", help="Bumpkin provider mode.")
    parser.add_argument(
        "--model",
        default=os.getenv("BUMPKIN_MODEL", "stub-model"),
        help="Model identifier passed through BUMPKIN_MODEL.",
    )
    parser.add_argument(
        "--endpoint",
        default=os.getenv("BUMPKIN_ENDPOINT", "http://127.0.0.1:9/v1/chat/completions"),
        help="Model endpoint passed through BUMPKIN_ENDPOINT.",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("BUMPKIN_API_KEY", ""),
        help="Optional model API key passed through BUMPKIN_API_KEY.",
    )
    parser.add_argument("--token-cap", type=int, default=6000)
    parser.add_argument("--output-json", default="", help="Optional result JSON path.")
    return parser.parse_args()


def _extract_payload(stdout: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    try:
        payload, _ = decoder.raw_decode(stdout.lstrip())
    except JSONDecodeError as err:
        raise RuntimeError("Bumpkin did not emit a JSON result.") from err
    if not isinstance(payload, dict):
        raise RuntimeError("Bumpkin emitted a JSON result that was not an object.")
    return payload


def _repository_root(path: Path) -> Path:
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip()).resolve()


def main() -> int:
    args = _parse_args()
    repository = _repository_root(Path(args.repository).resolve())
    project_root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(project_root / "src"), environment.get("PYTHONPATH", "")) if part
    )
    environment["BUMPKIN_API_KEY"] = args.api_key
    environment["BUMPKIN_MODEL"] = args.model
    environment["BUMPKIN_ENDPOINT"] = args.endpoint

    command = [
        sys.executable,
        str(project_root / "src" / "main.py"),
        "--mode",
        args.mode,
        "--from-ref",
        args.from_ref,
        "--to-ref",
        args.to_ref,
        "--token-cap",
        str(args.token_cap),
    ]
    result = subprocess.run(
        command,
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
    )
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    if result.returncode != 0:
        print(result.stdout, end="")
        return result.returncode

    payload = _extract_payload(result.stdout)
    if args.output_json:
        output_path = Path(args.output_json).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": payload.get("status"),
                "mode": payload.get("mode"),
                "language_group": payload.get("language_group"),
                "deterministic_label": payload.get("deterministic_label"),
                "failure_category": payload.get("failure_category"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
