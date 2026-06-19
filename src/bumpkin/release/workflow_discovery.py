from __future__ import annotations

import io
import json
import os
import urllib.parse
import zipfile
from typing import cast

from bumpkin.release.candidate import _coerce_int, _deserialize_release_candidate
from bumpkin.release.models import ReleaseCandidate
from bumpkin.release.repository_client import _bytes_request, _json_request


def _workflow_file_path() -> str | None:
    workflow_ref = os.getenv("GITHUB_WORKFLOW_REF", "").strip()
    if not workflow_ref:
        return None
    workflow_path = workflow_ref.split("@", 1)[0]
    marker = "/.github/workflows/"
    marker_index = workflow_path.find(marker)
    if marker_index == -1:
        return None
    return workflow_path[marker_index + 1 :].strip() or None


def _current_branch_name() -> str | None:
    branch_name = os.getenv("GITHUB_REF_NAME", "").strip()
    return branch_name or None


def _current_run_id() -> str | None:
    run_id = os.getenv("GITHUB_RUN_ID", "").strip()
    return run_id or None


def _list_workflow_runs(
    *,
    repository: str,
    token: str,
    workflow_file: str,
    branch: str | None,
    timeout_seconds: int,
    per_page: int,
) -> list[dict[str, object]]:
    encoded_workflow_file = urllib.parse.quote(workflow_file, safe="")
    query: list[str] = ["status=success", f"per_page={max(1, per_page)}"]
    if branch:
        query.append(f"branch={urllib.parse.quote(branch, safe='')}")
    url = (
        f"https://api.github.com/repos/{repository}/actions/workflows/{encoded_workflow_file}/runs"
        f"?{'&'.join(query)}"
    )
    payload = _json_request(token=token, url=url, timeout_seconds=timeout_seconds)
    if not isinstance(payload, dict):
        return []
    workflow_runs = cast("dict[str, object]", payload).get("workflow_runs")
    if not isinstance(workflow_runs, list):
        return []
    return [cast("dict[str, object]", item) for item in workflow_runs if isinstance(item, dict)]


def _list_run_artifacts(
    *,
    repository: str,
    token: str,
    run_id: str,
    timeout_seconds: int,
) -> list[dict[str, object]]:
    encoded_run_id = urllib.parse.quote(run_id, safe="")
    url = f"https://api.github.com/repos/{repository}/actions/runs/{encoded_run_id}/artifacts?per_page=100"
    payload = _json_request(token=token, url=url, timeout_seconds=timeout_seconds)
    if not isinstance(payload, dict):
        return []
    artifacts = cast("dict[str, object]", payload).get("artifacts")
    if not isinstance(artifacts, list):
        return []
    return [cast("dict[str, object]", item) for item in artifacts if isinstance(item, dict)]


def _download_release_candidate_for_run(
    *,
    repository: str,
    token: str,
    run_id: str,
    artifact_name: str,
    timeout_seconds: int,
) -> ReleaseCandidate | None:
    artifacts = _list_run_artifacts(
        repository=repository,
        token=token,
        run_id=run_id,
        timeout_seconds=timeout_seconds,
    )
    artifact_id: int | None = None
    for artifact in artifacts:
        if str(artifact.get("name", "")).strip() != artifact_name:
            continue
        if bool(artifact.get("expired", False)):
            continue
        artifact_id = _coerce_int(artifact.get("id", 0), field_name="id")
        break
    if artifact_id is None:
        return None

    url = f"https://api.github.com/repos/{repository}/actions/artifacts/{artifact_id}/zip"
    archive_bytes = _bytes_request(token=token, url=url, timeout_seconds=timeout_seconds)
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        json_entries = [name for name in archive.namelist() if name.endswith(".json")]
        if not json_entries:
            raise RuntimeError("Release candidate artifact did not contain a JSON payload.")
        with archive.open(json_entries[0]) as candidate_file:
            payload = json.load(candidate_file)
    return _deserialize_release_candidate(payload)


def _resolve_release_candidate(
    *,
    repository: str,
    token: str,
    preview_run_id: str,
    base_tag_input: str,
    artifact_name: str,
    timeout_seconds: int,
    discovery_limit: int,
) -> ReleaseCandidate:
    normalized_run_id = preview_run_id.strip()
    if normalized_run_id:
        candidate = _download_release_candidate_for_run(
            repository=repository,
            token=token,
            run_id=normalized_run_id,
            artifact_name=artifact_name,
            timeout_seconds=timeout_seconds,
        )
        if candidate is None:
            raise RuntimeError(
                f"No release candidate artifact named '{artifact_name}' was found on run {normalized_run_id}."
            )
        return candidate

    workflow_file = _workflow_file_path()
    if workflow_file is None:
        raise RuntimeError(
            "Unable to discover prior preview candidates automatically. Pass preview_run_id."
        )
    branch = _current_branch_name()
    current_run_id = _current_run_id()
    for workflow_run in _list_workflow_runs(
        repository=repository,
        token=token,
        workflow_file=workflow_file,
        branch=branch,
        timeout_seconds=timeout_seconds,
        per_page=discovery_limit,
    ):
        run_id = str(workflow_run.get("id", "")).strip()
        if not run_id or (current_run_id and run_id == current_run_id):
            continue
        candidate = _download_release_candidate_for_run(
            repository=repository,
            token=token,
            run_id=run_id,
            artifact_name=artifact_name,
            timeout_seconds=timeout_seconds,
        )
        if candidate is None:
            continue
        if candidate.source_operation != "release_preview":
            continue
        if candidate.repository != repository:
            continue
        if candidate.base_tag_input != base_tag_input:
            continue
        return candidate

    raise RuntimeError(
        "No matching release preview candidate was found. Run release_preview first or pass preview_run_id."
    )


__all__ = [
    "_current_branch_name",
    "_current_run_id",
    "_download_release_candidate_for_run",
    "_list_run_artifacts",
    "_list_workflow_runs",
    "_resolve_release_candidate",
    "_workflow_file_path",
]
