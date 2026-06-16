from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, Self

from bumpkin.integrations.github.events import (
    is_recommendation_merge_event,
    normalize_webhook_event,
)
from bumpkin.integrations.github.github_auth import GitHubAppInstallationTokenProvider
from bumpkin.integrations.github.ingress import (
    OUTCOME_ACCEPTED,
    OUTCOME_DUPLICATE_IGNORED,
    OUTCOME_REJECTED_SIGNATURE,
    OUTCOME_UNSUPPORTED_EVENT,
    OUTCOME_UNSUPPORTED_PROVIDER,
    DeliveryStore,
    InMemoryDeliveryStore,
    ingest_webhook_event,
)
from bumpkin.integrations.github.persistence import (
    AppStateStore,
    EphemeralAppStateStore,
    build_app_state_store,
)
from bumpkin.integrations.github.reactions import (
    GitHubIssueCommentPublisher,
    GitHubIssueCommentReactionPublisher,
    NoopReactionPublisher,
    ReactionPublisher,
    ReactionPublishRequest,
)
from bumpkin.integrations.github.recommendations import (
    GitHubRecommendationCommentPublisher,
    MergeRecommendationRequest,
    NoopRecommendationPublisher,
    PipelineRecommendationRunner,
    RecommendationPublisher,
    RecommendationRunner,
)
from bumpkin.integrations.github.release_aggregation import aggregate_release_backlog
from bumpkin.integrations.github.release_notes import render_release_notes
from bumpkin.integrations.github.releases import (
    GitHubReleasePublisher,
    NoopReleasePublisher,
    ReleasePublisher,
    ReleasePublishRequest,
)
from bumpkin.integrations.github.runtime import (
    APP_MODE_SHELL,
    BUMP_MISMATCH_POLICY_BLOCK,
    AppRuntimeConfig,
    load_app_runtime_config,
)
from bumpkin.integrations.github.tags import (
    GitHubTagPublisher,
    NoopTagPublisher,
    TagPublisher,
    TagPublishRequest,
)
from bumpkin.integrations.github.types import AppEvent, SlashCommand
from bumpkin.integrations.github.workflows import (
    GitHubWorkflowDispatcher,
    NoopWorkflowDispatcher,
    WorkflowDispatcher,
    WorkflowDispatchRequest,
)

_HEADER_EVENT_NAME = "x-github-event"
_VERSION_TOKEN_RE = re.compile(r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")
_NEXT_VERSION_LINE_RE = re.compile(r"(?im)^next version\s*:\s*.*$")
_VALID_BUMP_LABELS = frozenset({"MAJOR", "MINOR", "PATCH", "NO_BUMP"})
_DEFERRED_DEPLOY_STATUS_PREFIX = "deferred_deploy:"


@dataclass(frozen=True, slots=True)
class WebhookResponse:
    status_code: int
    payload: dict[str, Any]


class InstallationTokenProvider(Protocol):
    def get_token(self, installation_id: int | None) -> str | None: ...


def _normalize_headers(headers: Mapping[str, object]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in headers.items():
        normalized[str(key).strip().lower()] = str(value).strip()
    return normalized


def _status_for_outcome(outcome: str) -> int:
    if outcome == OUTCOME_ACCEPTED:
        return 202
    if outcome == OUTCOME_DUPLICATE_IGNORED:
        return 200
    if outcome == OUTCOME_REJECTED_SIGNATURE:
        return 401
    if outcome == OUTCOME_UNSUPPORTED_EVENT:
        return 202
    if outcome == OUTCOME_UNSUPPORTED_PROVIDER:
        return 400
    return 500


def _normalize_bump_label(token: str) -> str | None:
    normalized = token.strip().upper().replace("-", "_")
    if normalized == "NOBUMP":
        normalized = "NO_BUMP"
    if normalized in _VALID_BUMP_LABELS:
        return normalized
    return None


def _normalize_version_token(token: str) -> str | None:
    match = _VERSION_TOKEN_RE.match(token.strip())
    if not match:
        return None
    return f"{int(match.group('major'))}.{int(match.group('minor'))}.{int(match.group('patch'))}"


def _bump_semver(version: str, label: str) -> str:
    major, minor, patch = [int(part) for part in version.split(".")]
    if label == "MAJOR":
        if major == 0:
            return f"0.{minor + 1}.0"
        return f"{major + 1}.0.0"
    if label == "MINOR":
        return f"{major}.{minor + 1}.0"
    if label == "NO_BUMP":
        return f"{major}.{minor}.{patch}"
    return f"{major}.{minor}.{patch + 1}"


def _rewrite_recommendation_next_version(
    *,
    body: str,
    current_version: str | None,
    next_version: str | None,
) -> str:
    normalized_current = _normalize_version_token(current_version or "")
    normalized_next = _normalize_version_token(next_version or "")
    if normalized_current is None or normalized_next is None:
        return body
    line = f"Next version   : v{normalized_current} -> v{normalized_next}"
    if _NEXT_VERSION_LINE_RE.search(body):
        updated = _NEXT_VERSION_LINE_RE.sub(line, body, count=1)
    else:
        suffix = "" if body.endswith("\n") else "\n"
        updated = f"{body}{suffix}{line}\n"
    if not updated.endswith("\n"):
        updated += "\n"
    return updated


def _parse_bump_command_args(args: tuple[str, ...]) -> tuple[str, str | None, bool, bool]:
    filtered_args: list[str] = []
    force = False
    for token in args:
        normalized = token.strip()
        if not normalized:
            continue
        if normalized.lower() in {"--force", "force"}:
            force = True
            continue
        filtered_args.append(normalized)

    label = "PATCH"
    explicit_label = False
    if filtered_args:
        parsed_label = _normalize_bump_label(filtered_args[0])
        if parsed_label is not None:
            label = parsed_label
            explicit_label = True
            filtered_args = filtered_args[1:]

    version_token = filtered_args[0] if filtered_args else None
    return label, version_token, force, explicit_label


def _build_command_reaction(
    command: SlashCommand,
    *,
    recommended_label: str | None = None,
    recommended_current_version: str | None = None,
    mismatch_policy: str,
) -> dict[str, Any]:
    if command.name != "bump":
        return {"type": "command_received", "command": command.name}

    label, version_token, force, explicit_label = _parse_bump_command_args(command.args)
    normalized_recommendation = _normalize_bump_label(recommended_label or "")
    if normalized_recommendation is not None and not explicit_label:
        label = normalized_recommendation
    reaction: dict[str, Any] = {
        "type": "version_bump_suggestion",
        "command": "bump",
        "label": label,
    }
    if normalized_recommendation is not None:
        reaction["recommended_label"] = normalized_recommendation
        if explicit_label and normalized_recommendation != label:
            reaction["warning"] = (
                f"Requested label {label} overrides recommendation {normalized_recommendation}."
            )
            reaction["override"] = {
                "requested_label": label,
                "recommended_label": normalized_recommendation,
                "forced": force,
            }
            if mismatch_policy == BUMP_MISMATCH_POLICY_BLOCK and not force:
                reaction["applied"] = False
                reaction["policy"] = mismatch_policy
                reaction["message"] = (
                    f"Requested label {label} conflicts with recommendation "
                    f"{normalized_recommendation}. Re-run with --force to override."
                )
                return reaction

    if version_token is None:
        derived_version = _normalize_version_token(recommended_current_version or "")
        if derived_version is not None:
            version_token = derived_version
            reaction["derived_current_version"] = derived_version
        else:
            return {
                **reaction,
                "applied": False,
                "message": "Provide current version, e.g. /bump patch v1.2.3",
            }

    current_version = _normalize_version_token(version_token)
    if current_version is None:
        return {
            **reaction,
            "applied": False,
            "message": "Invalid version token. Expected semver like v1.2.3",
        }

    next_version = _bump_semver(current_version, label)
    return {
        **reaction,
        "applied": True,
        "policy": mismatch_policy,
        "current_version": current_version,
        "next_version": next_version,
        "message": f"Suggested next version: v{next_version}",
    }


def _mark_bump_not_applied_when_tag_failed(
    *,
    reaction: dict[str, Any],
    tag_delivery: Mapping[str, object] | None,
) -> dict[str, Any]:
    if reaction.get("type") != "version_bump_suggestion":
        return reaction
    if not bool(reaction.get("applied")):
        return reaction
    if not isinstance(tag_delivery, Mapping):
        return reaction
    status = str(tag_delivery.get("status", "")).strip().lower()
    if status != "failed":
        return reaction

    error_message = str(tag_delivery.get("message", "")).strip() or "tag publish failed"
    prior_message = str(reaction.get("message", "")).strip()
    updated = dict(reaction)
    updated["applied"] = False
    if prior_message:
        updated["message"] = f"{prior_message} Not applied: {error_message}"
    else:
        updated["message"] = f"Not applied: {error_message}"
    return updated


def _extract_pull_request_metadata(payload: Mapping[str, object]) -> dict[str, str | None]:
    pull_request = payload.get("pull_request")
    if not isinstance(pull_request, Mapping):
        return {
            "pull_request_title": None,
            "pull_request_author_login": None,
            "pull_request_url": None,
            "release_summary": None,
        }
    user = pull_request.get("user")
    author_login = None
    if isinstance(user, Mapping):
        author_login = str(user.get("login", "")).strip() or None
    title = str(pull_request.get("title", "")).strip() or None
    html_url = str(pull_request.get("html_url", "")).strip() or None
    return {
        "pull_request_title": title,
        "pull_request_author_login": author_login,
        "pull_request_url": html_url,
        "release_summary": title,
    }


def _is_release_command(command: SlashCommand) -> bool:
    if command.name == "bump" and command.args:
        first_arg = command.args[0].strip().lower()
        return first_arg in {"publish", "cut"}
    return False


def _is_shell_mode(config: AppRuntimeConfig) -> bool:
    return config.app_mode == APP_MODE_SHELL


def _extract_repository_default_branch(payload: Mapping[str, object]) -> str | None:
    repository = payload.get("repository")
    if not isinstance(repository, Mapping):
        return None
    default_branch = str(repository.get("default_branch", "")).strip()
    return default_branch or None


def _resolve_shell_operation(command: SlashCommand) -> tuple[str | None, str | None]:
    if command.name == "publish":
        remaining_args = command.args
        operation = "release_publish"
    elif command.name == "bump":
        if not command.args:
            return "release_preview", None
        first = command.args[0].strip().lower()
        if first in {"publish", "cut"}:
            remaining_args = command.args[1:]
            operation = "release_publish"
        elif first == "preview":
            remaining_args = command.args[1:]
            operation = "release_preview"
        elif _normalize_bump_label(first) is not None:
            return None, "Shell mode only supports `/bump`, `/bump preview`, and `/bump publish`."
        else:
            remaining_args = command.args
            operation = "release_preview"
    else:
        return None, "Shell mode currently supports only `/bump` and `/bump publish`."

    if len(remaining_args) > 1:
        return None, "Provide at most one base tag override, e.g. `/bump preview v1.2.3`."
    base_tag = remaining_args[0].strip() if remaining_args else None
    return operation, base_tag or None


class AppWebhookService:
    def __init__(
        self,
        *,
        config: AppRuntimeConfig,
        state_store: AppStateStore,
        delivery_store: DeliveryStore | None = None,
        reaction_publisher: ReactionPublisher | None = None,
        tag_publisher: TagPublisher | None = None,
        release_publisher: ReleasePublisher | None = None,
        recommendation_runner: RecommendationRunner | None = None,
        recommendation_publisher: RecommendationPublisher | None = None,
        installation_token_provider: InstallationTokenProvider | None = None,
        workflow_dispatcher: WorkflowDispatcher | None = None,
    ) -> None:
        self._config = config
        self._shell_mode = _is_shell_mode(config)
        self._state_store = state_store
        self._delivery_store = delivery_store or InMemoryDeliveryStore()
        self._recommendation_runner = recommendation_runner or PipelineRecommendationRunner()
        self._reaction_publisher = reaction_publisher
        self._tag_publisher = tag_publisher
        self._release_publisher = release_publisher
        self._recommendation_publisher = recommendation_publisher
        self._workflow_dispatcher = workflow_dispatcher
        if installation_token_provider is not None:
            self._installation_token_provider = installation_token_provider
        elif config.github_app_id and config.github_app_private_key:
            self._installation_token_provider = GitHubAppInstallationTokenProvider(
                app_id=config.github_app_id,
                private_key_pem=config.github_app_private_key,
            )
        else:
            self._installation_token_provider = None
        self._default_reaction_publisher = NoopReactionPublisher()
        self._default_tag_publisher = NoopTagPublisher()
        self._default_release_publisher = NoopReleasePublisher()
        self._default_recommendation_publisher = NoopRecommendationPublisher()
        self._self_repository = (config.self_repository or "").strip().lower() or None
        self._deployment_revision = (config.deployment_revision or "").strip() or None
        self._defer_self_merge_recommendation = (
            config.defer_self_merge_recommendation_until_new_deploy
        )
        if not self._shell_mode:
            self._replay_deferred_merge_recommendations_once()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def close(self) -> None:
        self._state_store.close()

    def _resolve_provider_token(self, event: AppEvent | None) -> str | None:
        if self._installation_token_provider is not None and event is not None:
            app_token = self._installation_token_provider.get_token(event.installation_id)
            if app_token is not None:
                return app_token
        return self._config.provider_token

    def _resolve_workflow_dispatcher(self, event: AppEvent | None) -> WorkflowDispatcher:
        if self._workflow_dispatcher is not None:
            return self._workflow_dispatcher
        token = self._resolve_provider_token(event)
        if token is not None:
            return GitHubWorkflowDispatcher(token=token)
        return NoopWorkflowDispatcher()

    def _deferred_status_value(self) -> str:
        revision = self._deployment_revision or "unknown"
        return f"{_DEFERRED_DEPLOY_STATUS_PREFIX}{revision}"

    def _should_defer_merge_recommendation(self, event: AppEvent) -> bool:
        if not self._defer_self_merge_recommendation:
            return False
        if self._self_repository is None or self._deployment_revision is None:
            return False
        if not is_recommendation_merge_event(event):
            return False
        repository = (event.repository or "").strip().lower()
        if repository != self._self_repository:
            return False
        if (event.base_ref or "").strip() != "main":
            return False
        merge_commit_sha = (event.merge_commit_sha or "").strip()
        if not merge_commit_sha:
            return False
        return merge_commit_sha != self._deployment_revision

    def _replay_deferred_merge_recommendations_once(self) -> None:
        if not self._defer_self_merge_recommendation:
            return
        if self._self_repository is None or self._deployment_revision is None:
            return
        try:
            deferred_events = self._state_store.list_deferred_merge_events(
                provider="github",
                repository=self._self_repository,
                limit=20,
            )
        except Exception:  # noqa: BLE001 - startup catch-up should not crash service boot
            return

        for stored_event in deferred_events:
            deferred_revision = (
                stored_event.status.removeprefix(_DEFERRED_DEPLOY_STATUS_PREFIX)
                if stored_event.status.startswith(_DEFERRED_DEPLOY_STATUS_PREFIX)
                else None
            )
            if deferred_revision == self._deployment_revision:
                continue
            event = normalize_webhook_event(
                "pull_request",
                stored_event.payload,
                delivery_id=stored_event.provider_event_id,
            )
            if event is None or not is_recommendation_merge_event(event):
                continue
            if (event.base_ref or "").strip() != "main":
                continue
            self._process_merge_recommendation(
                event=event,
                payload=stored_event.payload,
                response_payload=None,
            )

    def _has_pending_self_deferred_merge_for_current_deploy(self) -> bool:
        if not self._defer_self_merge_recommendation:
            return False
        if self._self_repository is None or self._deployment_revision is None:
            return False
        deferred_status = self._deferred_status_value()
        try:
            deferred_events = self._state_store.list_deferred_merge_events(
                provider="github",
                repository=self._self_repository,
                limit=20,
            )
        except Exception:  # noqa: BLE001 - defer checks must not crash webhook handling
            return False
        return any(event.status == deferred_status for event in deferred_events)

    def _process_merge_recommendation(
        self,
        *,
        event: AppEvent,
        payload: Mapping[str, object],
        response_payload: dict[str, Any] | None,
    ) -> None:
        recommendation_body: str | None = None
        try:
            provider_token = self._resolve_provider_token(event)
            recommendation_request = MergeRecommendationRequest(
                event=event,
                payload=payload,
                provider_token=provider_token,
            )
            recommendation = self._recommendation_runner.generate(recommendation_request)
            recommendation_body = recommendation.body
        except Exception as err:  # noqa: BLE001 - recommendation generation failures are surfaced
            if response_payload is not None:
                response_payload["recommendation"] = {
                    "status": "failed",
                    "reason": "runner_error",
                    "message": str(err).strip() or "recommendation generation failed",
                }
            return

        if response_payload is not None:
            response_payload["recommendation"] = {
                "status": "generated",
                "label": recommendation.label,
                "current_version": recommendation.current_version,
            }
        if (
            recommendation.label is not None
            and event.repository is not None
            and event.pull_request_number is not None
        ):
            try:
                self._state_store.record_recommendation_snapshot(
                    repository=event.repository,
                    pull_request_number=event.pull_request_number,
                    label=recommendation.label,
                    current_version=recommendation.current_version,
                    source="app_merge",
                    source_event_id=event.delivery_id,
                )
            except Exception as err:  # noqa: BLE001 - persistence failures should not fail ingress
                if response_payload is not None:
                    response_payload["recommendation_persistence"] = {
                        "status": "failed",
                        "reason": "store_error",
                        "message": str(err).strip() or "recommendation snapshot persistence failed",
                    }
            else:
                if response_payload is not None:
                    response_payload["recommendation_persistence"] = {"status": "stored"}
            try:
                merge_commit_sha = (
                    event.merge_commit_sha or event.head_sha or event.base_sha or ""
                ).strip()
                if not merge_commit_sha:
                    merge_commit_sha = f"unknown-pr-{event.pull_request_number}"
                pr_metadata = _extract_pull_request_metadata(payload)
                backlog_id = self._state_store.upsert_release_backlog_item(
                    repository=event.repository,
                    pull_request_number=event.pull_request_number,
                    merge_commit_sha=merge_commit_sha,
                    recommended_label=recommendation.label,
                    recommended_current_version=recommendation.current_version,
                    pull_request_title=pr_metadata["pull_request_title"],
                    pull_request_author_login=pr_metadata["pull_request_author_login"],
                    pull_request_url=pr_metadata["pull_request_url"],
                    release_summary=pr_metadata["release_summary"],
                    source_event_id=event.delivery_id,
                )
            except Exception as err:  # noqa: BLE001 - backlog persistence failures should not fail ingress
                if response_payload is not None:
                    response_payload["release_backlog"] = {
                        "status": "failed",
                        "reason": "store_error",
                        "message": str(err).strip() or "release backlog persistence failed",
                    }
            else:
                if response_payload is not None:
                    response_payload["release_backlog"] = {
                        "status": "upserted",
                        "id": backlog_id,
                    }
                try:
                    backlog_items = self._state_store.list_unreleased_release_backlog_items(
                        repository=event.repository,
                    )
                except Exception:  # noqa: BLE001 - preview should not fail recommendation handling
                    backlog_items = []
                if backlog_items:
                    aggregate = aggregate_release_backlog(backlog_items)
                    recommendation_body = _rewrite_recommendation_next_version(
                        body=recommendation_body or recommendation.body,
                        current_version=aggregate.current_version,
                        next_version=aggregate.next_version,
                    )
                    if response_payload is not None:
                        response_payload["release_preview"] = {
                            "status": "computed",
                            "baseline_version": aggregate.current_version,
                            "highest_unreleased_label": aggregate.recommended_label
                            or aggregate.aggregated_label,
                            "next_version": aggregate.next_version,
                        }
        try:
            recommendation_publisher = self._recommendation_publisher
            if recommendation_publisher is None:
                token = self._resolve_provider_token(event)
                if token is not None:
                    recommendation_publisher = GitHubRecommendationCommentPublisher(token=token)
                else:
                    recommendation_publisher = self._default_recommendation_publisher
            published_url = recommendation_publisher.publish(
                repository=event.repository or "",
                issue_number=event.pull_request_number or 0,
                body=recommendation_body or recommendation.body,
            )
        except Exception as err:  # noqa: BLE001 - publishing failures should not fail ingress
            if response_payload is not None:
                response_payload["recommendation_delivery"] = {
                    "status": "failed",
                    "reason": "publisher_error",
                    "message": str(err).strip() or "recommendation publish failed",
                }
            return
        if response_payload is not None:
            if published_url:
                response_payload["recommendation_delivery"] = {
                    "status": "posted",
                    "url": published_url,
                }
            else:
                response_payload["recommendation_delivery"] = {
                    "status": "skipped",
                    "reason": "publisher_unavailable",
                }

    def _process_shell_command(
        self,
        *,
        event: AppEvent,
        payload: Mapping[str, object],
        command: SlashCommand,
        response_payload: dict[str, Any],
    ) -> None:
        if event.repository is None:
            response_payload["reaction"] = {
                "type": "workflow_dispatch_requested",
                "applied": False,
                "message": "Cannot dispatch a release workflow without a repository context.",
            }
            return

        operation, error_message = _resolve_shell_operation(command)
        if operation is None:
            response_payload["reaction"] = {
                "type": "workflow_dispatch_requested",
                "applied": False,
                "message": error_message or "Unsupported shell command.",
            }
            return

        base_tag = None
        if command.name == "publish":
            remaining_args = command.args
        elif command.args and command.args[0].strip().lower() in {"publish", "cut", "preview"}:
            remaining_args = command.args[1:]
        else:
            remaining_args = command.args
        if remaining_args:
            base_tag = remaining_args[0].strip() or None

        dispatch_ref = (
            _extract_repository_default_branch(payload)
            or self._config.release_workflow_ref
            or event.base_ref
            or "main"
        )
        dispatcher = self._resolve_workflow_dispatcher(event)
        request = WorkflowDispatchRequest(
            repository=event.repository,
            workflow_id=self._config.release_workflow_file,
            ref=dispatch_ref,
            operation=operation,
            base_tag=base_tag,
            installation_id=event.installation_id,
        )
        try:
            result = dispatcher.dispatch(request)
        except Exception as err:  # noqa: BLE001 - dispatch failures should not fail ingress
            response_payload["workflow_dispatch"] = {
                "status": "failed",
                "reason": "dispatcher_error",
                "workflow_id": request.workflow_id,
                "operation": request.operation,
                "ref": request.ref,
                "message": str(err).strip() or "workflow dispatch failed",
            }
            response_payload["reaction"] = {
                "type": "workflow_dispatch_requested",
                "applied": False,
                "workflow_id": request.workflow_id,
                "operation": request.operation,
                "ref": request.ref,
                "base_tag": request.base_tag,
                "message": response_payload["workflow_dispatch"]["message"],
            }
            return

        response_payload["workflow_dispatch"] = {
            "status": result.status,
            "workflow_id": result.workflow_id,
            "operation": result.operation,
            "ref": result.ref,
        }
        if result.base_tag:
            response_payload["workflow_dispatch"]["base_tag"] = result.base_tag
        if result.url:
            response_payload["workflow_dispatch"]["url"] = result.url
        if result.message:
            response_payload["workflow_dispatch"]["message"] = result.message

        response_payload["reaction"] = {
            "type": "workflow_dispatch_requested",
            "applied": result.status == "queued",
            "workflow_id": result.workflow_id,
            "operation": result.operation,
            "ref": result.ref,
            "base_tag": result.base_tag,
            "workflow_url": result.url,
            "message": result.message
            or (
                "Queued release preview workflow."
                if result.operation == "release_preview"
                else "Queued release publish workflow."
            ),
        }

    def _process_release_command(
        self,
        *,
        event: AppEvent,
        response_payload: dict[str, Any],
    ) -> None:
        if event.repository is None:
            response_payload["release"] = {
                "status": "failed",
                "reason": "missing_repository",
            }
            return

        try:
            backlog_items = self._state_store.list_unreleased_release_backlog_items(
                repository=event.repository,
            )
        except Exception:  # noqa: BLE001 - backlog read errors should not fail release handling
            backlog_items = []

        response_payload["release_backlog"] = {
            "status": "loaded",
            "items": len(backlog_items),
        }
        if not backlog_items:
            response_payload["release"] = {
                "status": "skipped",
                "reason": "no_unreleased_items",
            }
            return

        aggregate = aggregate_release_backlog(backlog_items)
        release_label = aggregate.recommended_label or aggregate.aggregated_label
        current_version = aggregate.current_version
        next_version = aggregate.next_version
        if not next_version:
            response_payload["release"] = {
                "status": "skipped",
                "reason": "missing_next_version",
            }
            return

        tag_name = f"v{next_version}"
        target_sha = (
            (aggregate.target_merge_commit_sha or "").strip()
            or (event.merge_commit_sha or "").strip()
            or (event.head_sha or "").strip()
            or (event.base_sha or "").strip()
        )
        if not target_sha:
            response_payload["release"] = {
                "status": "skipped",
                "reason": "missing_target_sha",
            }
            return

        release_notes = render_release_notes(
            tag_name=tag_name,
            items=backlog_items,
            current_version=current_version,
            next_version=next_version,
            release_label=release_label,
        )
        response_payload["release_notes"] = {
            "status": "rendered",
            "tag_name": tag_name,
            "included_prs": len(backlog_items),
            "release_label": release_label,
        }

        tag_request = TagPublishRequest(
            repository=event.repository,
            tag_name=tag_name,
            target_sha=target_sha,
            installation_id=event.installation_id,
        )
        try:
            tag_publisher = self._tag_publisher
            if tag_publisher is None:
                token = self._resolve_provider_token(event)
                if token is not None:
                    tag_publisher = GitHubTagPublisher(token=token)
                else:
                    tag_publisher = self._default_tag_publisher
            tag_result = tag_publisher.publish(tag_request)
        except Exception as err:  # noqa: BLE001 - tag publish failures should not fail webhook intake
            response_payload["tag_delivery"] = {
                "status": "failed",
                "reason": "publisher_error",
                "message": str(err).strip() or "tag publish failed",
            }
            response_payload["release"] = {
                "status": "failed",
                "reason": "tag_publish_failed",
            }
            return

        response_payload["tag_delivery"] = {
            "status": tag_result.status,
            "tag_name": tag_result.tag_name,
            "target_sha": target_sha,
        }
        if tag_result.url:
            response_payload["tag_delivery"]["url"] = tag_result.url
        if tag_result.message:
            response_payload["tag_delivery"]["message"] = tag_result.message
        if tag_result.status not in {"created", "exists"}:
            response_payload["release"] = {
                "status": "skipped",
                "reason": "tag_publish_skipped",
            }
            return

        release_request = ReleasePublishRequest(
            repository=event.repository,
            tag_name=tag_name,
            target_sha=target_sha,
            body=release_notes,
            name=tag_name,
            installation_id=event.installation_id,
        )
        try:
            release_publisher = self._release_publisher
            if release_publisher is None:
                token = self._resolve_provider_token(event)
                if token is not None:
                    release_publisher = GitHubReleasePublisher(token=token)
                else:
                    release_publisher = self._default_release_publisher
            release_result = release_publisher.publish(release_request)
        except Exception as err:  # noqa: BLE001 - release publish failures should not fail webhook intake
            response_payload["release_delivery"] = {
                "status": "failed",
                "reason": "publisher_error",
                "message": str(err).strip() or "release publish failed",
            }
            response_payload["release"] = {
                "status": "failed",
                "reason": "release_publish_failed",
            }
            return

        response_payload["release_delivery"] = {
            "status": release_result.status,
            "tag_name": release_result.tag_name,
        }
        if release_result.url:
            response_payload["release_delivery"]["url"] = release_result.url
        if release_result.message:
            response_payload["release_delivery"]["message"] = release_result.message

        if release_result.status in {"created", "updated"}:
            try:
                included_count = self._state_store.mark_release_backlog_items_included(
                    repository=event.repository,
                    backlog_ids=aggregate.considered_item_ids,
                    release_tag=tag_name,
                )
            except Exception as err:  # noqa: BLE001 - inclusion failures should not fail webhook intake
                response_payload["release_backlog_update"] = {
                    "status": "failed",
                    "reason": "store_error",
                    "message": str(err).strip() or "release backlog inclusion update failed",
                }
            else:
                response_payload["release_backlog_update"] = {
                    "status": "marked_included",
                    "release_tag": tag_name,
                    "updated_count": included_count,
                }

        response_payload["release"] = {
            "status": "published",
            "tag_name": tag_name,
            "release_url": release_result.url or response_payload["release_delivery"].get("url"),
            "included_prs": len(backlog_items),
        }

    def handle_github_webhook(
        self,
        *,
        headers: Mapping[str, object],
        raw_body: bytes,
    ) -> WebhookResponse:
        normalized_headers = _normalize_headers(headers)
        event_name = normalized_headers.get(_HEADER_EVENT_NAME, "").strip()
        if not event_name:
            return WebhookResponse(
                status_code=400,
                payload={
                    "accepted": False,
                    "outcome": "invalid_request",
                    "reason": "missing_event_name",
                },
            )

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return WebhookResponse(
                status_code=400,
                payload={
                    "accepted": False,
                    "outcome": "invalid_request",
                    "reason": "invalid_payload_json",
                },
            )
        if not isinstance(payload, dict):
            return WebhookResponse(
                status_code=400,
                payload={
                    "accepted": False,
                    "outcome": "invalid_request",
                    "reason": "payload_must_be_object",
                },
            )

        result = ingest_webhook_event(
            provider="github",
            event_name=event_name,
            payload=payload,
            headers=headers,
            webhook_secret=self._config.webhook_secret,
            delivery_store=self._delivery_store,
            event_store=self._state_store,
            raw_body=raw_body,
        )
        response_payload: dict[str, Any] = {
            "accepted": result.accepted,
            "outcome": result.outcome,
            "reason": result.reason,
        }
        if result.event is not None:
            response_payload["event"] = {
                "event": result.event.event,
                "delivery_id": result.event.delivery_id,
                "repository": result.event.repository,
                "pull_request_number": result.event.pull_request_number,
                "merged": result.event.merged,
                "merge_commit_sha": result.event.merge_commit_sha,
                "base_ref": result.event.base_ref,
                "base_sha": result.event.base_sha,
                "head_ref": result.event.head_ref,
                "head_sha": result.event.head_sha,
            }
        if (
            result.event is not None
            and result.envelope is not None
            and is_recommendation_merge_event(result.event)
        ):
            if self._shell_mode:
                response_payload["recommendation"] = {
                    "status": "skipped",
                    "reason": "shell_mode_release_scoped",
                }
            elif self._should_defer_merge_recommendation(result.event):
                deferred_status = self._deferred_status_value()
                updated = False
                if result.event.delivery_id is not None:
                    updated = self._state_store.update_event_status(
                        provider="github",
                        provider_event_id=result.event.delivery_id,
                        status=deferred_status,
                    )
                response_payload["recommendation"] = {
                    "status": "deferred",
                    "reason": "awaiting_new_deploy",
                    "deployment_revision": self._deployment_revision,
                }
                response_payload["recommendation_defer"] = {
                    "status": "recorded" if updated else "not_recorded",
                    "event_status": deferred_status,
                }
            else:
                self._process_merge_recommendation(
                    event=result.event,
                    payload=result.envelope.payload,
                    response_payload=response_payload,
                )
        if (
            not self._shell_mode
            and result.command is not None
            and result.event is not None
            and result.event.repository is not None
            and self._self_repository is not None
            and self._deployment_revision is not None
            and result.event.repository.strip().lower() == self._self_repository
            and self._has_pending_self_deferred_merge_for_current_deploy()
        ):
            response_payload["command"] = {
                "name": result.command.name,
                "args": list(result.command.args),
            }
            response_payload["reaction"] = {
                "type": "command_deferred",
                "command": result.command.name,
                "applied": False,
                "message": "Command deferred until a new app deploy is active.",
            }
            response_payload["command_defer"] = {
                "status": "deferred",
                "reason": "awaiting_new_deploy",
                "deployment_revision": self._deployment_revision,
            }
            return WebhookResponse(
                status_code=_status_for_outcome(result.outcome),
                payload=response_payload,
            )
        if result.command is not None and self._shell_mode:
            response_payload["command"] = {
                "name": result.command.name,
                "args": list(result.command.args),
            }
            if result.event is None:
                response_payload["reaction"] = {
                    "type": "workflow_dispatch_requested",
                    "applied": False,
                    "message": "Shell commands require repository context.",
                }
            else:
                self._process_shell_command(
                    event=result.event,
                    payload=payload,
                    command=result.command,
                    response_payload=response_payload,
                )
            if result.event is not None and result.event.repository is not None:
                publish_request = ReactionPublishRequest(
                    repository=result.event.repository,
                    issue_number=result.event.pull_request_number or 0,
                    command_name=result.command.name,
                    command_args=result.command.args,
                    command_raw=result.command.raw,
                    reaction=response_payload["reaction"],
                    comment_id=result.event.comment_id,
                    comment_html_url=result.event.comment_html_url,
                    installation_id=result.event.installation_id,
                )
                try:
                    reaction_publisher = self._reaction_publisher
                    if reaction_publisher is None:
                        token = self._resolve_provider_token(result.event)
                        if token is not None:
                            reaction_publisher = GitHubIssueCommentReactionPublisher(token=token)
                        else:
                            reaction_publisher = self._default_reaction_publisher
                    published_url = reaction_publisher.publish(publish_request)
                except Exception as err:  # noqa: BLE001 - reaction delivery must not fail webhook intake
                    response_payload["reaction_delivery"] = {
                        "status": "failed",
                        "reason": "publisher_error",
                        "message": str(err).strip() or "reaction publish failed",
                    }
                else:
                    if published_url:
                        response_payload["reaction_delivery"] = {
                            "status": "posted",
                            "url": published_url,
                        }
            return WebhookResponse(
                status_code=_status_for_outcome(result.outcome),
                payload=response_payload,
            )
        if result.command is not None:
            response_payload["command"] = {
                "name": result.command.name,
                "args": list(result.command.args),
            }
            recommended_label: str | None = None
            recommended_current_version: str | None = None
            release_backlog_ids_to_include: tuple[int, ...] = ()
            release_target_merge_sha: str | None = None
            if _is_release_command(result.command):
                if result.event is not None and result.event.repository is not None:
                    self._process_release_command(
                        event=result.event,
                        response_payload=response_payload,
                    )
                release_status = str(response_payload.get("release", {}).get("status", "")).strip()
                response_payload["reaction"] = {
                    "type": "release_published" if release_status == "published" else "release_cut",
                    "applied": release_status == "published",
                    "tag_name": response_payload.get("release", {}).get("tag_name"),
                    "release_url": response_payload.get("release", {}).get("release_url"),
                    "included_prs": response_payload.get("release", {}).get("included_prs"),
                    "message": (
                        f"Published release {response_payload.get('release', {}).get('tag_name')}"
                        if release_status == "published"
                        else str(
                            response_payload.get("release", {}).get(
                                "reason", "release not published"
                            )
                        )
                    ),
                }
            else:
                if (
                    result.command.name == "bump"
                    and result.event is not None
                    and result.event.repository is not None
                    and result.event.pull_request_number is not None
                ):
                    try:
                        backlog_items = self._state_store.list_unreleased_release_backlog_items(
                            repository=result.event.repository,
                        )
                    except Exception:  # noqa: BLE001 - backlog read errors should not fail command handling
                        backlog_items = []
                    if backlog_items:
                        aggregate = aggregate_release_backlog(backlog_items)
                        recommended_label = (
                            aggregate.recommended_label or aggregate.aggregated_label
                        )
                        recommended_current_version = aggregate.current_version
                        release_backlog_ids_to_include = aggregate.considered_item_ids
                        release_target_merge_sha = aggregate.target_merge_commit_sha
                        response_payload["release_backlog"] = {
                            "status": "loaded",
                            "items": aggregate.item_count,
                            "considered_items": aggregate.considered_item_count,
                            "considered_backlog_ids": list(aggregate.considered_item_ids),
                            "aggregated_label": aggregate.aggregated_label,
                            "recommended_label": aggregate.recommended_label,
                            "baseline_version": aggregate.baseline_version,
                            "current_version": aggregate.current_version,
                            "next_version": aggregate.next_version,
                            "target_merge_commit_sha": aggregate.target_merge_commit_sha,
                        }
                    if recommended_label is None or recommended_current_version is None:
                        recommendation = self._state_store.latest_recommendation_for_pr(
                            repository=result.event.repository,
                            pull_request_number=result.event.pull_request_number,
                        )
                        if recommendation is not None:
                            if recommended_label is None:
                                recommended_label = recommendation.label
                            if recommended_current_version is None:
                                recommended_current_version = recommendation.current_version
                response_payload["reaction"] = _build_command_reaction(
                    result.command,
                    recommended_label=recommended_label,
                    recommended_current_version=recommended_current_version,
                    mismatch_policy=self._config.bump_mismatch_policy,
                )
                if (
                    result.command.name == "bump"
                    and result.event is not None
                    and result.event.repository is not None
                    and result.event.pull_request_number is not None
                ):
                    reaction = response_payload["reaction"]
                    if bool(reaction.get("applied")):
                        next_version = str(reaction.get("next_version", "")).strip()
                        tag_name = f"v{next_version}" if next_version else ""
                        target_sha = (
                            (release_target_merge_sha or "").strip()
                            or (result.event.merge_commit_sha or "").strip()
                            or (result.event.head_sha or "").strip()
                            or (result.event.base_sha or "").strip()
                        )
                        if not tag_name:
                            response_payload["tag_delivery"] = {
                                "status": "skipped",
                                "reason": "missing_next_version",
                            }
                        elif not target_sha:
                            response_payload["tag_delivery"] = {
                                "status": "skipped",
                                "reason": "missing_target_sha",
                            }
                        else:
                            tag_request = TagPublishRequest(
                                repository=result.event.repository,
                                tag_name=tag_name,
                                target_sha=target_sha,
                                installation_id=result.event.installation_id,
                            )
                            try:
                                tag_publisher = self._tag_publisher
                                if tag_publisher is None:
                                    token = self._resolve_provider_token(result.event)
                                    if token is not None:
                                        tag_publisher = GitHubTagPublisher(token=token)
                                    else:
                                        tag_publisher = self._default_tag_publisher
                                tag_result = tag_publisher.publish(tag_request)
                            except Exception as err:  # noqa: BLE001 - tag publish failures should not fail webhook intake
                                response_payload["tag_delivery"] = {
                                    "status": "failed",
                                    "reason": "publisher_error",
                                    "message": str(err).strip() or "tag publish failed",
                                }
                            else:
                                response_payload["tag_delivery"] = {
                                    "status": tag_result.status,
                                    "tag_name": tag_result.tag_name,
                                    "target_sha": target_sha,
                                }
                                if tag_result.url:
                                    response_payload["tag_delivery"]["url"] = tag_result.url
                                if tag_result.message:
                                    response_payload["tag_delivery"]["message"] = tag_result.message
                                if (
                                    tag_result.status in {"created", "exists"}
                                    and release_backlog_ids_to_include
                                ):
                                    try:
                                        included_count = (
                                            self._state_store.mark_release_backlog_items_included(
                                                repository=result.event.repository,
                                                backlog_ids=release_backlog_ids_to_include,
                                                release_tag=tag_name,
                                            )
                                        )
                                    except Exception as err:  # noqa: BLE001 - inclusion failures should not fail webhook intake
                                        response_payload["release_backlog_update"] = {
                                            "status": "failed",
                                            "reason": "store_error",
                                            "message": str(err).strip()
                                            or "release backlog inclusion update failed",
                                        }
                                    else:
                                        response_payload["release_backlog_update"] = {
                                            "status": "marked_included",
                                            "release_tag": tag_name,
                                            "updated_count": included_count,
                                        }
                    response_payload["reaction"] = _mark_bump_not_applied_when_tag_failed(
                        reaction=reaction,
                        tag_delivery=response_payload.get("tag_delivery"),
                    )
            if result.event is not None and result.event.repository is not None:
                publish_request = ReactionPublishRequest(
                    repository=result.event.repository,
                    issue_number=result.event.pull_request_number or 0,
                    command_name=result.command.name,
                    command_args=result.command.args,
                    command_raw=result.command.raw,
                    reaction=response_payload["reaction"],
                    comment_id=result.event.comment_id,
                    comment_html_url=result.event.comment_html_url,
                    installation_id=result.event.installation_id,
                )
                try:
                    reaction_publisher = self._reaction_publisher
                    if reaction_publisher is None:
                        token = self._resolve_provider_token(result.event)
                        if token is not None:
                            reaction_publisher = GitHubIssueCommentPublisher(token=token)
                        else:
                            reaction_publisher = self._default_reaction_publisher
                    published_url = reaction_publisher.publish(publish_request)
                except Exception as err:  # noqa: BLE001 - reaction delivery must not fail webhook intake
                    response_payload["reaction_delivery"] = {
                        "status": "failed",
                        "reason": "publisher_error",
                        "message": str(err).strip() or "reaction publish failed",
                    }
                else:
                    if published_url:
                        response_payload["reaction_delivery"] = {
                            "status": "posted",
                            "url": published_url,
                        }
        return WebhookResponse(
            status_code=_status_for_outcome(result.outcome),
            payload=response_payload,
        )


def build_app_webhook_service(
    *,
    config: AppRuntimeConfig,
    state_store: AppStateStore | None = None,
    delivery_store: DeliveryStore | None = None,
    reaction_publisher: ReactionPublisher | None = None,
    tag_publisher: TagPublisher | None = None,
    release_publisher: ReleasePublisher | None = None,
    recommendation_runner: RecommendationRunner | None = None,
    recommendation_publisher: RecommendationPublisher | None = None,
    installation_token_provider: InstallationTokenProvider | None = None,
    workflow_dispatcher: WorkflowDispatcher | None = None,
) -> AppWebhookService:
    return AppWebhookService(
        config=config,
        state_store=state_store
        or (
            EphemeralAppStateStore()
            if config.app_mode == APP_MODE_SHELL
            and config.db_path is None
            and config.database_url is None
            else build_app_state_store(
                db_path=config.db_path,
                database_url=config.database_url,
            )
        ),
        delivery_store=delivery_store,
        reaction_publisher=reaction_publisher,
        tag_publisher=tag_publisher,
        release_publisher=release_publisher,
        recommendation_runner=recommendation_runner,
        recommendation_publisher=recommendation_publisher,
        installation_token_provider=installation_token_provider,
        workflow_dispatcher=workflow_dispatcher,
    )


def build_app_webhook_service_from_env(
    environ: Mapping[str, str] | None = None,
) -> AppWebhookService:
    return build_app_webhook_service(
        config=load_app_runtime_config(environ),
    )
