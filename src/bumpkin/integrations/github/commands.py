from __future__ import annotations

from bumpkin.integrations.github.types import SlashCommand

SUPPORTED_SLASH_COMMANDS = frozenset({"approve", "bump", "publish", "explain"})
_BUMP_SHORTHAND = frozenset({"major", "minor", "patch", "no_bump", "no-bump", "nobump"})


def parse_slash_command(body: str) -> SlashCommand | None:
    for raw_line in body.splitlines():
        line = " ".join(raw_line.strip().split())
        if not line:
            continue
        parts = line.split()
        command_name = ""
        args: tuple[str, ...] = ()
        prefix = parts[0].lower()
        if prefix == "/bumpkin":
            if len(parts) < 2:
                continue
            candidate = parts[1].lower()
            if candidate in SUPPORTED_SLASH_COMMANDS:
                command_name = candidate
                args = tuple(parts[2:])
            elif candidate in _BUMP_SHORTHAND:
                command_name = "bump"
                args = tuple(parts[1:])
            else:
                return None
        elif prefix == "/bump":
            command_name = "bump"
            args = tuple(parts[1:])
        else:
            continue
        if command_name not in SUPPORTED_SLASH_COMMANDS:
            return None
        return SlashCommand(name=command_name, args=args, raw=line)
    return None
