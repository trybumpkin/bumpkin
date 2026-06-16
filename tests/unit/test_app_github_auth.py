from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from bumpkin.integrations.github.github_auth import GitHubAppInstallationTokenProvider


class _FakeInstallationTokenProvider(GitHubAppInstallationTokenProvider):
    def __init__(self) -> None:
        super().__init__(
            app_id="12345",
            private_key_pem="-----BEGIN KEY-----\nabc\n-----END KEY-----",
            refresh_margin_seconds=60,
        )
        self.jwt_calls = 0
        self.api_calls: list[tuple[str, str, str]] = []
        self.responses: list[dict[str, object]] = []

    def _build_app_jwt(self, *, now: datetime) -> str:  # noqa: ARG002
        self.jwt_calls += 1
        return "app-jwt-token"

    def _api_request(
        self,
        *,
        url: str,
        method: str,
        bearer_token: str,
        payload: dict[str, object] | None = None,  # noqa: ARG002
    ) -> object:
        self.api_calls.append((url, method, bearer_token))
        return self.responses.pop(0)


def test_installation_token_provider_caches_valid_tokens() -> None:
    provider = _FakeInstallationTokenProvider()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)  # noqa: UP017
    provider.responses.append(
        {
            "token": "installation-token-1",
            "expires_at": expires_at.isoformat(),
        }
    )

    first = provider.get_token(42)
    second = provider.get_token(42)

    assert first == "installation-token-1"
    assert second == "installation-token-1"
    assert provider.jwt_calls == 1
    assert provider.api_calls == [
        ("https://api.github.com/app/installations/42/access_tokens", "POST", "app-jwt-token")
    ]


def test_installation_token_provider_refreshes_expiring_tokens() -> None:
    provider = _FakeInstallationTokenProvider()
    now = datetime.now(timezone.utc)  # noqa: UP017
    provider.responses.extend(
        [
            {
                "token": "installation-token-1",
                "expires_at": (now + timedelta(seconds=30)).isoformat(),
            },
            {
                "token": "installation-token-2",
                "expires_at": (now + timedelta(minutes=5)).isoformat(),
            },
        ]
    )

    first = provider.get_token(42)
    second = provider.get_token(42)

    assert first == "installation-token-1"
    assert second == "installation-token-2"
    assert provider.jwt_calls == 2
    assert len(provider.api_calls) == 2


def test_installation_token_provider_rejects_missing_token_in_response() -> None:
    provider = _FakeInstallationTokenProvider()
    provider.responses.append({"expires_at": datetime.now(timezone.utc).isoformat()})  # noqa: UP017

    with pytest.raises(RuntimeError, match="did not include `token`"):
        provider.get_token(42)
