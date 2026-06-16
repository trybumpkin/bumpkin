from bumpkin.integrations.github.commands import parse_slash_command


def test_parse_slash_command_approve() -> None:
    command = parse_slash_command("/bumpkin approve")
    assert command is not None
    assert command.name == "approve"
    assert command.args == ()


def test_parse_slash_command_publish_with_args() -> None:
    command = parse_slash_command("/bumpkin publish patch v1.2.3")
    assert command is not None
    assert command.name == "publish"
    assert command.args == ("patch", "v1.2.3")


def test_parse_slash_command_multiline_comment_uses_first_valid_line() -> None:
    command = parse_slash_command(
        "Looks good to me.\n\n/bumpkin explain why this is minor\n\nThanks!"
    )
    assert command is not None
    assert command.name == "explain"
    assert command.args == ("why", "this", "is", "minor")


def test_parse_slash_command_rejects_unknown_subcommand() -> None:
    assert parse_slash_command("/bumpkin dance") is None


def test_parse_slash_command_rejects_non_command_text() -> None:
    assert parse_slash_command("ship it") is None


def test_parse_slash_command_supports_bump_alias_prefix() -> None:
    command = parse_slash_command("/bump patch v1.2.3")
    assert command is not None
    assert command.name == "bump"
    assert command.args == ("patch", "v1.2.3")


def test_parse_slash_command_supports_bump_under_bumpkin_prefix() -> None:
    command = parse_slash_command("/bumpkin bump minor v2.3.4")
    assert command is not None
    assert command.name == "bump"
    assert command.args == ("minor", "v2.3.4")


def test_parse_slash_command_supports_bump_shorthand_under_bumpkin_prefix() -> None:
    command = parse_slash_command("/bumpkin minor v2.3.4")
    assert command is not None
    assert command.name == "bump"
    assert command.args == ("minor", "v2.3.4")


def test_parse_slash_command_supports_bump_alias_without_args() -> None:
    command = parse_slash_command("/bump")
    assert command is not None
    assert command.name == "bump"
    assert command.args == ()
