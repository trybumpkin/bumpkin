from token_env import (
    OPENROUTER_ENDPOINT,
    is_openrouter_endpoint,
    is_valid_models_endpoint,
    resolve_models_endpoint,
    resolve_models_token,
)


def _clear_model_env(monkeypatch) -> None:
    for name in (
        "BUMPKIN_API_KEY",
        "BUMPKIN_ENDPOINT",
        "BUMPKIN_MODELS_ENDPOINT",
        "GITHUB_MODELS_ENDPOINT",
        "OPENROUTER_ENDPOINT",
        "MODELS_TOKEN",
        "GITHUB_MODELS_TOKEN",
        "OPENROUTER_API_KEY",
        "OPENROUTER_API",
    ):
        monkeypatch.delenv(name, raising=False)


def test_resolve_models_token_prefers_bumpkin_api_key(monkeypatch) -> None:
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("BUMPKIN_API_KEY", "bumpkin-api-key")
    monkeypatch.setenv("MODELS_TOKEN", "legacy-token")
    monkeypatch.setenv("GITHUB_TOKEN", "github-token")

    assert resolve_models_token() == "bumpkin-api-key"


def test_resolve_models_token_supports_legacy_models_token(monkeypatch) -> None:
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("MODELS_TOKEN", "legacy-token")

    assert resolve_models_token() == "legacy-token"


def test_resolve_models_token_returns_empty_without_model_provider_token(monkeypatch) -> None:
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("GITHUB_TOKEN", "github-token")

    assert resolve_models_token() == ""


def test_resolve_models_token_uses_bumpkin_api_key_for_openrouter(monkeypatch) -> None:
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("BUMPKIN_API_KEY", "bumpkin-api-key")
    monkeypatch.setenv("OPENROUTER_API", "legacy-openrouter-token")

    assert (
        resolve_models_token(endpoint="https://openrouter.ai/api/v1/chat/completions")
        == "bumpkin-api-key"
    )


def test_resolve_models_endpoint_prefers_bumpkin_endpoint(monkeypatch) -> None:
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("BUMPKIN_ENDPOINT", "https://example.com/canonical")
    monkeypatch.setenv("BUMPKIN_MODELS_ENDPOINT", "https://example.com/legacy")

    assert resolve_models_endpoint() == "https://example.com/canonical"


def test_resolve_models_endpoint_supports_legacy_openrouter_env(monkeypatch) -> None:
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_ENDPOINT", OPENROUTER_ENDPOINT)

    assert resolve_models_endpoint() == OPENROUTER_ENDPOINT


def test_resolve_models_endpoint_returns_empty_when_unset(monkeypatch) -> None:
    _clear_model_env(monkeypatch)

    assert resolve_models_endpoint() == ""


def test_is_openrouter_endpoint_detects_hostname() -> None:
    assert is_openrouter_endpoint("https://openrouter.ai/api/v1/chat/completions")
    assert not is_openrouter_endpoint("https://models.github.ai/inference/chat/completions")


def test_is_valid_models_endpoint_requires_http_scheme() -> None:
    assert is_valid_models_endpoint("https://generativelanguage.googleapis.com/v1beta/openai/")
    assert is_valid_models_endpoint("http://localhost:1234/v1/chat/completions")
    assert not is_valid_models_endpoint("generativelanguage.googleapis.com/v1beta/openai/")
    assert not is_valid_models_endpoint("***")
    assert not is_valid_models_endpoint("")
