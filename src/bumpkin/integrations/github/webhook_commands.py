from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from bumpkin.integrations.github.runtime import (
    APP_MODE_SHELL,
    BUMP_MISMATCH_POLICY_BLOCK,
    AppRuntimeConfig,
)
from bumpkin.integrations.github.types import SlashCommand
from bumpkin.integrations.github.webhook_parsing import (
    _normalize_bump_label,
    _normalize_version_token,
)


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


def _is_release_command(command: SlashCommand) -> bool:
    if command.name == "bump" and command.args:
        first_arg = command.args[0].strip().lower()
        return first_arg in {"publish", "cut"}
    return False


def _is_shell_mode(config: AppRuntimeConfig) -> bool:
    return config.app_mode == APP_MODE_SHELL


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


__all__ = [
    "_build_command_reaction",
    "_bump_semver",
    "_is_release_command",
    "_is_shell_mode",
    "_mark_bump_not_applied_when_tag_failed",
    "_parse_bump_command_args",
    "_resolve_shell_operation",
]
