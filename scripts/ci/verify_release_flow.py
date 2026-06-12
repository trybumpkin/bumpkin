from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_PATH = _REPO_ROOT / "src"
if str(_SRC_PATH) not in sys.path:
    sys.path.insert(0, str(_SRC_PATH))

from bumpkin.release_job import _deserialize_release_candidate

MAINTAINER_ONLY_SECTIONS = (
    "## Release rationale",
    "## Versioning context",
    "## Key evidence",
)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SystemExit(f"Expected file was not found: {path}") from exc


def _load_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(_read_text(path))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Expected JSON file was invalid: {path}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"Expected JSON object payload in: {path}")
    return payload


def _require_contains(text: str, needle: str, *, context: str) -> None:
    if needle not in text:
        raise SystemExit(f"Expected {context} to contain: {needle}")


def _require_absent(text: str, needle: str, *, context: str) -> None:
    if needle in text:
        raise SystemExit(f"Expected {context} to omit: {needle}")


def _validate_candidate(candidate: dict[str, object], *, expected_repository: str) -> None:
    try:
        _deserialize_release_candidate(candidate)
    except (RuntimeError, TypeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    if str(candidate.get("repository", "")).strip() != expected_repository:
        raise SystemExit("Release candidate repository did not match the expected repository.")
    if not str(candidate.get("fingerprint", "")).strip():
        raise SystemExit("Release candidate fingerprint was missing.")
    if not str(candidate.get("source_operation", "")).strip():
        raise SystemExit("Release candidate source_operation was missing.")
    if str(candidate.get("source_operation", "")).strip() != "release_preview":
        raise SystemExit("Release candidate source_operation must be release_preview.")
    if not isinstance(candidate.get("pull_requests"), list):
        raise SystemExit("Release candidate pull_requests payload was missing.")


def _validate_preview(
    *,
    notes_text: str,
    candidate: dict[str, object],
    expected_status: str,
) -> None:
    status = str(candidate.get("status", "")).strip()
    if expected_status and status != expected_status:
        raise SystemExit(
            f"Release candidate status mismatch. Expected {expected_status!r}, got {status!r}."
        )
    if status == "planned":
        _require_contains(notes_text, "## Release rationale", context="preview notes")
        _require_contains(notes_text, "## Versioning context", context="preview notes")
        _require_contains(notes_text, "## Key evidence", context="preview notes")
        _require_contains(notes_text, "## Public release notes", context="preview notes")
        return
    if status == "needs_review":
        _require_contains(notes_text, "## Public release notes", context="preview notes")
        _require_contains(notes_text, "### Needs Review", context="preview notes")
        return
    if status == "skipped":
        if (
            "No new release will be published for this batch." not in notes_text
            and "No merged pull requests were found in this release scope." not in notes_text
        ):
            raise SystemExit(
                "Skipped preview notes must explain whether the batch was NO_BUMP or empty."
            )
        return
    raise SystemExit(f"Unsupported preview status for verification: {status!r}.")


def _validate_publish(
    *,
    notes_text: str,
    candidate: dict[str, object],
    expected_status: str,
) -> None:
    for heading in MAINTAINER_ONLY_SECTIONS:
        _require_absent(notes_text, heading, context="published release body")
    if expected_status != "published":
        raise SystemExit("Publish verification currently requires expected_status='published'.")
    expected_body = candidate.get("published_release_body", "")
    if not isinstance(expected_body, str):
        raise SystemExit("Release candidate published_release_body was invalid.")
    if notes_text != expected_body:
        raise SystemExit("Published release body did not match the saved release candidate body.")
    if "## " not in notes_text:
        raise SystemExit("Published release body did not contain any changelog sections.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate Bumpkin preview and publish release flow artifacts."
    )
    parser.add_argument("--mode", choices=("preview", "publish"), required=True)
    parser.add_argument("--notes-path", required=True)
    parser.add_argument("--candidate-path", required=True)
    parser.add_argument("--expected-repository", required=True)
    parser.add_argument("--expected-status", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    notes_path = Path(args.notes_path)
    candidate_path = Path(args.candidate_path)

    notes_text = _read_text(notes_path)
    candidate = _load_json(candidate_path)
    _validate_candidate(candidate, expected_repository=args.expected_repository)

    if args.mode == "preview":
        _validate_preview(
            notes_text=notes_text,
            candidate=candidate,
            expected_status=args.expected_status,
        )
    else:
        _validate_publish(
            notes_text=notes_text,
            candidate=candidate,
            expected_status=args.expected_status,
        )

    print(
        "Bumpkin release flow validation passed:"
        f" mode={args.mode} status={args.expected_status} repository={args.expected_repository}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
