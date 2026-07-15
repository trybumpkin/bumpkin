from __future__ import annotations

import os
from urllib.parse import urlparse

GITHUB_MODELS_ENDPOINT = "https://models.github.ai/inference/chat/completions"
OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


def is_openrouter_endpoint(endpoint: str | None) -> bool:
    if not endpoint:
        return False
    return "openrouter.ai" in endpoint.strip().lower()


def is_github_models_endpoint(endpoint: str | None) -> bool:
    if not endpoint:
        return False
    return "models.github.ai" in endpoint.strip().lower()


def is_valid_models_endpoint(endpoint: str | None) -> bool:
    if not endpoint:
        return False
    normalized = endpoint.strip()
    if not normalized:
        return False
    parsed = urlparse(normalized)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def resolve_models_endpoint() -> str:
    explicit = (
        os.getenv("BUMPKIN_ENDPOINT")
        or os.getenv("BUMPKIN_MODELS_ENDPOINT")
        or os.getenv("GITHUB_MODELS_ENDPOINT")
        or os.getenv("OPENROUTER_ENDPOINT")
    )
    if explicit and explicit.strip():
        return explicit.strip()
    return ""


def resolve_models_token(*, endpoint: str | None = None) -> str:
    normalized_endpoint = endpoint or resolve_models_endpoint()
    api_key = os.getenv("BUMPKIN_API_KEY")
    if api_key and api_key.strip():
        return api_key.strip()

    if is_openrouter_endpoint(normalized_endpoint):
        return (
            os.getenv("OPENROUTER_API")
            or os.getenv("OPENROUTER_API_KEY")
            or os.getenv("MODELS_TOKEN")
            or os.getenv("GITHUB_MODELS_TOKEN")
            or ""
        )

    return (
        os.getenv("MODELS_TOKEN")
        or os.getenv("GITHUB_MODELS_TOKEN")
        or os.getenv("OPENROUTER_API_KEY")
        or os.getenv("OPENROUTER_API")
        or ""
    )


__all__ = [
    "GITHUB_MODELS_ENDPOINT",
    "OPENROUTER_ENDPOINT",
    "is_github_models_endpoint",
    "is_openrouter_endpoint",
    "is_valid_models_endpoint",
    "resolve_models_endpoint",
    "resolve_models_token",
]
