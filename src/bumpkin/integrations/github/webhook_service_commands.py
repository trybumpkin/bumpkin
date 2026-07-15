from __future__ import annotations

from typing import Any

from bumpkin.integrations.github.types import SlashCommand


def build_command_payload(command: SlashCommand) -> dict[str, Any]:
    return {"name": command.name, "args": list(command.args)}


def build_deferred_command_response(
    *,
    command: SlashCommand,
    deployment_revision: str | None,
) -> dict[str, dict[str, Any]]:
    return {
        "command": build_command_payload(command),
        "reaction": {
            "type": "command_deferred",
            "command": command.name,
            "applied": False,
            "message": "Command deferred until a new app deploy is active.",
        },
        "command_defer": {
            "status": "deferred",
            "reason": "awaiting_new_deploy",
            "deployment_revision": deployment_revision,
        },
    }
