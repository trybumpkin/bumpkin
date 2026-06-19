from __future__ import annotations

import json
import os
from pathlib import Path

from bumpkin.release.models import ReleaseCandidate, ReleasePlan


def _render_publish_step_summary(
    *,
    status: str,
    plan: ReleasePlan,
    release_candidate: ReleaseCandidate,
    release_url: str | None = None,
    tag_url: str | None = None,
) -> str:
    title = {
        "published": "# Release published",
        "skipped": "# Release publish skipped",
        "needs_review": "# Release publish blocked",
    }.get(status, "# Release publish result")
    lines = [title, ""]
    if plan.previous_tag:
        lines.append(f"Previous tag: {plan.previous_tag}")
    if plan.next_tag:
        lines.append(
            f"Published tag: {plan.next_tag}"
            if status == "published"
            else f"Candidate tag: {plan.next_tag}"
        )
    if plan.release_label:
        lines.append(f"Release type: {plan.release_label}")
    lines.append(f"Included PRs: {len(plan.pull_requests)}")
    if release_candidate.source_run_id:
        lines.append(f"Preview run id: {release_candidate.source_run_id}")
    if status == "published":
        lines.append("Release candidate verified and published.")
    elif status == "skipped":
        lines.append("No release was published for this candidate.")
    elif status == "needs_review":
        lines.append("Release candidate still needs maintainer review before publish.")
    if release_url:
        lines.append(f"Release URL: {release_url}")
    if tag_url:
        lines.append(f"Tag URL: {tag_url}")
    return "\n".join(lines).strip() + "\n"


def _write_text_file(path_value: str, content: str) -> str:
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path)


def _write_json_file(path_value: str, payload: dict[str, object]) -> str:
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(path)


def _write_github_output(values: dict[str, str]) -> None:
    output_path = os.getenv("GITHUB_OUTPUT", "").strip()
    if not output_path:
        return
    lines: list[str] = []
    for key, value in values.items():
        lines.append(f"{key}<<__BUMPKIN_EOF__")
        lines.append(value)
        lines.append("__BUMPKIN_EOF__")
    with Path(output_path).open("a", encoding="utf-8") as output_file:
        output_file.write("\n".join(lines) + "\n")


def _append_step_summary(markdown: str) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY", "").strip()
    if not summary_path:
        return
    with Path(summary_path).open("a", encoding="utf-8") as summary_file:
        summary_file.write(markdown.rstrip() + "\n")


def _build_summary_payload(
    *,
    status: str,
    plan: ReleasePlan,
    release_candidate: ReleaseCandidate,
    candidate_path: str,
    release_candidate_artifact_name: str,
    release_url: str | None = None,
    tag_url: str | None = None,
    notes_path: str,
) -> dict[str, str]:
    return {
        "release_status": status,
        "release_previous_tag": plan.previous_tag or "",
        "release_next_tag": plan.next_tag or "",
        "release_label": plan.release_label or "",
        "release_pr_count": str(len(plan.pull_requests)),
        "release_notes_path": notes_path,
        "release_target_sha": plan.target_sha,
        "release_candidate_path": candidate_path,
        "release_candidate_fingerprint": release_candidate.fingerprint,
        "release_candidate_run_id": release_candidate.source_run_id or "",
        "release_candidate_artifact_name": release_candidate_artifact_name,
        "release_url": release_url or "",
        "tag_url": tag_url or "",
    }


__all__ = [
    "_append_step_summary",
    "_build_summary_payload",
    "_render_publish_step_summary",
    "_write_github_output",
    "_write_json_file",
    "_write_text_file",
]
