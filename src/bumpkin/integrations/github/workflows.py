from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Protocol
from urllib.parse import quote

from bumpkin.integrations.github.http_client import DEFAULT_GITHUB_HTTP_CLIENT, GitHubHttpClient


@dataclass(frozen=True, slots=True)
class WorkflowDispatchRequest:
    repository: str
    workflow_id: str
    ref: str
    operation: str
    base_tag: str | None = None
    installation_id: int | None = None


@dataclass(frozen=True, slots=True)
class WorkflowDispatchResult:
    status: str
    repository: str
    workflow_id: str
    ref: str
    operation: str
    url: str | None = None
    message: str | None = None
    base_tag: str | None = None


class WorkflowDispatcher(Protocol):
    def dispatch(self, request: WorkflowDispatchRequest) -> WorkflowDispatchResult: ...


class NoopWorkflowDispatcher:
    def dispatch(self, request: WorkflowDispatchRequest) -> WorkflowDispatchResult:
        return WorkflowDispatchResult(
            status="skipped",
            repository=request.repository,
            workflow_id=request.workflow_id,
            ref=request.ref,
            operation=request.operation,
            base_tag=request.base_tag,
            message="Workflow dispatcher is unavailable.",
        )


class GitHubWorkflowDispatcher:
    def __init__(
        self,
        *,
        token: str,
        user_agent: str = "bumpkin-app",
        timeout_seconds: int = 10,
        http_client: GitHubHttpClient = DEFAULT_GITHUB_HTTP_CLIENT,
    ) -> None:
        self._token = token.strip()
        self._user_agent = user_agent.strip() or "bumpkin-app"
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client

    def dispatch(self, request: WorkflowDispatchRequest) -> WorkflowDispatchResult:
        if not self._token:
            return WorkflowDispatchResult(
                status="skipped",
                repository=request.repository,
                workflow_id=request.workflow_id,
                ref=request.ref,
                operation=request.operation,
                base_tag=request.base_tag,
                message="GitHub workflow dispatch token is unavailable.",
            )

        workflow_id = request.workflow_id.strip()
        ref = request.ref.strip()
        url = (
            f"https://api.github.com/repos/{request.repository}/actions/workflows/"
            f"{quote(workflow_id, safe='')}/dispatches"
        )
        inputs: dict[str, str] = {"operation": request.operation}
        if request.base_tag is not None and request.base_tag.strip():
            inputs["base_tag"] = request.base_tag.strip()
        payload = {"ref": ref, "inputs": inputs}
        self._http_client.request_bytes(
            url=url,
            method="POST",
            timeout_seconds=self._timeout_seconds,
            token=self._token,
            user_agent=self._user_agent,
            payload=payload,
        )
        workflow_page = PurePosixPath(workflow_id).name
        return WorkflowDispatchResult(
            status="queued",
            repository=request.repository,
            workflow_id=workflow_id,
            ref=ref,
            operation=request.operation,
            base_tag=request.base_tag,
            url=f"https://github.com/{request.repository}/actions/workflows/{workflow_page}",
            message=f"Queued `{request.operation}` on `{ref}`.",
        )
