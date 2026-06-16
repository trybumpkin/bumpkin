from __future__ import annotations

from bumpkin.integrations.github.reactions import (
    REACTION_COMMENT_MARKER,
    NoopReactionPublisher,
    ReactionPublishRequest,
    format_reaction_comment,
    reaction_emoji_for_request,
)


def test_format_reaction_comment_for_applied_bump() -> None:
    request = ReactionPublishRequest(
        repository="acme/repo",
        issue_number=7,
        command_name="bump",
        command_args=("force", "minor"),
        command_raw="/bump force minor",
        reaction={
            "type": "version_bump_suggestion",
            "applied": True,
            "policy": "allow_with_warning",
            "label": "MINOR",
            "recommended_label": "PATCH",
            "derived_current_version": "1.2.3",
            "next_version": "1.3.0",
            "warning": "Requested label MINOR overrides recommendation PATCH.",
            "message": "Suggested next version: v1.3.0",
        },
    )

    body = format_reaction_comment(request)

    assert REACTION_COMMENT_MARKER in body
    assert "Command: `/bump force minor`" in body
    assert "Recommended label: `PATCH`" in body
    assert "Applied label: `MINOR`" in body
    assert "Version: `v1.2.3` -> `v1.3.0`" in body
    assert "Result: `applied`" in body


def test_noop_reaction_publisher_returns_none() -> None:
    publisher = NoopReactionPublisher()
    request = ReactionPublishRequest(
        repository="acme/repo",
        issue_number=7,
        command_name="bump",
        command_args=(),
        command_raw="/bump",
        reaction={"type": "version_bump_suggestion", "applied": False, "label": "PATCH"},
    )
    assert publisher.publish(request) is None


def test_reaction_emoji_for_shell_preview_request() -> None:
    request = ReactionPublishRequest(
        repository="acme/repo",
        issue_number=7,
        command_name="bump",
        command_args=(),
        command_raw="/bump",
        reaction={
            "type": "workflow_dispatch_requested",
            "operation": "release_preview",
            "applied": True,
        },
        comment_id=123,
        comment_html_url="https://github.com/acme/repo/pull/7#issuecomment-123",
    )

    assert reaction_emoji_for_request(request) == "eyes"


def test_reaction_emoji_for_shell_publish_request() -> None:
    request = ReactionPublishRequest(
        repository="acme/repo",
        issue_number=7,
        command_name="bump",
        command_args=("publish",),
        command_raw="/bump publish",
        reaction={
            "type": "workflow_dispatch_requested",
            "operation": "release_publish",
            "applied": True,
        },
        comment_id=123,
        comment_html_url="https://github.com/acme/repo/pull/7#issuecomment-123",
    )

    assert reaction_emoji_for_request(request) == "rocket"
