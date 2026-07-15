from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bumpkin.integrations.github.events import is_recommendation_merge_event
from bumpkin.integrations.github.ingress import IngressResult
from bumpkin.integrations.github.types import AppEvent
from bumpkin.integrations.github.webhook_service_command_flow import (
    handle_issue_comment_command,
    handle_shell_mode_command,
)
from bumpkin.integrations.github.webhook_service_commands import build_deferred_command_response
from bumpkin.integrations.github.webhook_service_deferred import (
    deferred_status_value,
    has_pending_self_deferred_merge_for_current_deploy,
    should_defer_merge_recommendation,
)
from bumpkin.integrations.github.webhook_service_payloads import build_event_payload

if TYPE_CHECKING:
    from bumpkin.integrations.github.webhook_runtime import WebhookRuntime


class WebhookDispatchCoordinator:
    def __init__(self, runtime: WebhookRuntime) -> None:
        self._runtime = runtime

    def dispatch(
        self,
        *,
        result: IngressResult,
        payload: dict[str, Any],
        response_payload: dict[str, Any],
    ) -> None:
        self._dispatch_recommendation(result=result, response_payload=response_payload)
        if self._has_deferred_command(result=result, response_payload=response_payload):
            return
        self._dispatch_command(result=result, payload=payload, response_payload=response_payload)

    def _dispatch_recommendation(
        self, *, result: IngressResult, response_payload: dict[str, Any]
    ) -> None:
        event = result.event
        if event is not None:
            response_payload["event"] = build_event_payload(event)
        if event is None or result.envelope is None:
            return
        if not is_recommendation_merge_event(event):
            return
        if self._runtime._shell_mode:
            response_payload["recommendation"] = {
                "status": "skipped",
                "reason": "shell_mode_release_scoped",
            }
            return
        if self._should_defer_recommendation(event):
            self._record_deferred_recommendation(event, response_payload)
            return
        self._runtime._effects.process_merge_recommendation(
            event=event,
            payload=result.envelope.payload,
            response_payload=response_payload,
        )

    def _should_defer_recommendation(self, event: AppEvent) -> bool:
        return should_defer_merge_recommendation(
            event,
            defer_self_merge_recommendation=self._runtime._defer_self_merge_recommendation,
            self_repository=self._runtime._self_repository,
            deployment_revision=self._runtime._deployment_revision,
        )

    def _record_deferred_recommendation(
        self, event: AppEvent, response_payload: dict[str, Any]
    ) -> None:
        deferred_status = deferred_status_value(self._runtime._deployment_revision)
        updated = bool(
            event.delivery_id
            and self._runtime._state_store.update_event_status(
                provider="github",
                provider_event_id=event.delivery_id,
                status=deferred_status,
            )
        )
        response_payload["recommendation"] = {
            "status": "deferred",
            "reason": "awaiting_new_deploy",
            "deployment_revision": self._runtime._deployment_revision,
        }
        response_payload["recommendation_defer"] = {
            "status": "recorded" if updated else "not_recorded",
            "event_status": deferred_status,
        }

    def _has_deferred_command(
        self, *, result: IngressResult, response_payload: dict[str, Any]
    ) -> bool:
        if not self._is_deferred_command_context(result):
            return False
        command = result.command
        if command is None:
            return False
        response_payload.update(
            build_deferred_command_response(
                command=command,
                deployment_revision=self._runtime._deployment_revision,
            )
        )
        return True

    def _is_deferred_command_context(self, result: IngressResult) -> bool:
        event = result.event
        return bool(
            not self._runtime._shell_mode
            and result.command is not None
            and event is not None
            and event.repository is not None
            and self._runtime._self_repository is not None
            and self._runtime._deployment_revision is not None
            and event.repository.strip().lower() == self._runtime._self_repository
            and has_pending_self_deferred_merge_for_current_deploy(
                defer_self_merge_recommendation=self._runtime._defer_self_merge_recommendation,
                self_repository=self._runtime._self_repository,
                deployment_revision=self._runtime._deployment_revision,
                state_store=self._runtime._state_store,
            )
        )

    def _dispatch_command(
        self,
        *,
        result: IngressResult,
        payload: dict[str, Any],
        response_payload: dict[str, Any],
    ) -> None:
        command = result.command
        if command is None:
            return
        if self._runtime._shell_mode:
            handle_shell_mode_command(
                event=result.event,
                payload=payload,
                command=command,
                response_payload=response_payload,
                configured_reaction_publisher=self._runtime._providers.configured_reaction_publisher,
                default_reaction_publisher=self._runtime._providers.default_reaction_publisher,
                resolve_provider_token=self._runtime._providers.resolve_provider_token,
                process_shell_command_fn=self._runtime._effects.process_shell_command,
            )
            return
        handle_issue_comment_command(
            event=result.event,
            command=command,
            response_payload=response_payload,
            mismatch_policy=self._runtime._config.bump_mismatch_policy,
            state_store=self._runtime._state_store,
            resolve_tag_publisher=self._runtime._providers.resolve_tag_publisher,
            process_release_command_fn=self._runtime._effects.process_release_command,
            configured_reaction_publisher=self._runtime._providers.configured_reaction_publisher,
            default_reaction_publisher=self._runtime._providers.default_reaction_publisher,
            resolve_provider_token=self._runtime._providers.resolve_provider_token,
        )
