from __future__ import annotations

import importlib

from bumpkin.integrations.github.releases import ReleasePublisher as IntegrationReleasePublisher


def test_github_package_reexports_release_publisher() -> None:
    from bumpkin.github import ReleasePublisher

    assert ReleasePublisher is IntegrationReleasePublisher


def test_github_releases_module_remains_importable() -> None:
    module = importlib.import_module("bumpkin.github.releases")

    assert module.ReleasePublisher is IntegrationReleasePublisher
