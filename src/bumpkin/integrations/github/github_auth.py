from __future__ import annotations

import base64
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from typing import Any

from bumpkin.integrations.github.http_client import DEFAULT_GITHUB_HTTP_CLIENT, GitHubHttpClient

_GITHUB_API_VERSION = "2022-11-28"


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _parse_timestamp(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)  # noqa: UP017
    return parsed.astimezone(timezone.utc)  # noqa: UP017


def _sign_jwt_rs256(*, private_key_pem: str, payload: bytes) -> bytes:
    with NamedTemporaryFile("w", encoding="utf-8", delete=False) as key_file:
        key_file.write(private_key_pem)
        key_path = Path(key_file.name)

    try:
        try:
            process = subprocess.run(
                ["openssl", "dgst", "-sha256", "-binary", "-sign", str(key_path)],
                input=payload,
                capture_output=True,
                check=False,
            )
        except FileNotFoundError as err:
            raise RuntimeError("openssl is required to sign GitHub App JWTs.") from err

        if process.returncode != 0:
            stderr = process.stderr.decode("utf-8", errors="replace").strip()
            message = stderr or "openssl failed to sign JWT."
            raise RuntimeError(f"GitHub App JWT signing failed: {message}")
        return process.stdout
    finally:
        key_path.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class _CachedInstallationToken:
    token: str
    expires_at: datetime
    refresh_after: datetime


class GitHubAppInstallationTokenProvider:
    def __init__(
        self,
        *,
        app_id: str,
        private_key_pem: str,
        user_agent: str = "bumpkin-app",
        timeout_seconds: int = 10,
        refresh_margin_seconds: int = 60,
        jwt_ttl_seconds: int = 540,
        http_client: GitHubHttpClient = DEFAULT_GITHUB_HTTP_CLIENT,
    ) -> None:
        normalized_app_id = app_id.strip()
        normalized_private_key = private_key_pem.strip()
        if not normalized_app_id:
            raise ValueError("GitHub App token provider requires a non-empty app_id.")
        if not normalized_private_key:
            raise ValueError("GitHub App token provider requires a non-empty private_key_pem.")
        if refresh_margin_seconds < 0:
            raise ValueError("refresh_margin_seconds must be non-negative.")
        if jwt_ttl_seconds < 60:
            raise ValueError("jwt_ttl_seconds must be at least 60 seconds.")

        self._app_id = normalized_app_id
        self._private_key_pem = normalized_private_key
        self._user_agent = user_agent.strip() or "bumpkin-app"
        self._timeout_seconds = timeout_seconds
        self._refresh_margin = timedelta(seconds=refresh_margin_seconds)
        self._jwt_ttl_seconds = min(jwt_ttl_seconds, 540)
        self._http_client = http_client
        self._cache: dict[int, _CachedInstallationToken] = {}
        self._lock = Lock()

    def get_token(self, installation_id: int | None) -> str | None:
        if installation_id is None:
            return None
        if installation_id <= 0:
            raise ValueError("installation_id must be a positive integer.")

        now = datetime.now(timezone.utc)  # noqa: UP017 - keep basedpyright compatibility
        with self._lock:
            cached = self._cache.get(installation_id)
            if cached is not None and now < cached.refresh_after:
                return cached.token

        token, expires_at = self._request_installation_token(
            installation_id=installation_id, now=now
        )
        refresh_after = expires_at - self._refresh_margin
        with self._lock:
            self._cache[installation_id] = _CachedInstallationToken(
                token=token,
                expires_at=expires_at,
                refresh_after=refresh_after,
            )
        return token

    def _build_app_jwt(self, *, now: datetime) -> str:
        issued_at = int(now.timestamp()) - 60
        expires_at = issued_at + self._jwt_ttl_seconds
        header = {"alg": "RS256", "typ": "JWT"}
        claims = {"iat": issued_at, "exp": expires_at, "iss": self._app_id}

        encoded_header = _base64url_encode(
            json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        encoded_claims = _base64url_encode(
            json.dumps(claims, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        signing_input = f"{encoded_header}.{encoded_claims}".encode("ascii")
        signature = _sign_jwt_rs256(private_key_pem=self._private_key_pem, payload=signing_input)
        encoded_signature = _base64url_encode(signature)
        return f"{encoded_header}.{encoded_claims}.{encoded_signature}"

    def _request_installation_token(
        self,
        *,
        installation_id: int,
        now: datetime,
    ) -> tuple[str, datetime]:
        app_jwt = self._build_app_jwt(now=now)
        response = self._api_request(
            url=f"https://api.github.com/app/installations/{installation_id}/access_tokens",
            method="POST",
            payload={},
            bearer_token=app_jwt,
        )

        if not isinstance(response, dict):
            raise RuntimeError("GitHub App token response was not a JSON object.")
        token_value = str(response.get("token", "")).strip()
        expires_raw = str(response.get("expires_at", "")).strip()
        if not token_value:
            raise RuntimeError("GitHub App token response did not include `token`.")
        if not expires_raw:
            raise RuntimeError("GitHub App token response did not include `expires_at`.")
        return token_value, _parse_timestamp(expires_raw)

    def _api_request(
        self,
        *,
        url: str,
        method: str,
        bearer_token: str,
        payload: dict[str, Any] | None = None,
    ) -> object:
        response, _headers = self._http_client.request_json(
            url=url,
            method=method,
            timeout_seconds=self._timeout_seconds,
            bearer_token=bearer_token,
            user_agent=self._user_agent,
            payload=payload,
            extra_headers={"X-GitHub-Api-Version": _GITHUB_API_VERSION},
        )
        return response
