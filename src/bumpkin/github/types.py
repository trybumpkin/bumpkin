"""Compatibility facade for legacy GitHub type imports."""

from bumpkin.integrations.github.types import AppEvent, SlashCommand

__all__ = ["AppEvent", "SlashCommand"]
