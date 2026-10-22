"""Spec 003, T003: environment-aware settings, secrets as SecretStr and fail-fast in prod."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from betting_ml.config import PROJECT_ROOT, InsecureConfigError, Settings, ensure_secure

ARGON2_HASH = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHRzYWx0$aGFzaGhhc2hoYXNoaGFzaA"
SECRET_KEY = "k-" + "A1b2C3d4" * 5
SECRET_SESSION = "s-" + "Z9y8X7w6" * 5


def secure_prod(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "app_env": "prod",
        "app_password_hash": ARGON2_HASH,
        "app_api_key": SECRET_KEY,
        "session_secret": SECRET_SESSION,
        "allowed_hosts": ["bets.example.com"],
        "cors_origins": ["https://bets.example.com"],
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_dev_defaults_start_without_secrets() -> None:
    settings = Settings(_env_file=None)
    assert settings.app_env == "dev"
    ensure_secure(settings)  # dev never blocks the start
    assert settings.allowed_hosts == ["localhost", "127.0.0.1"]
    assert "http://localhost:5173" in settings.cors_origins
    assert settings.effective_log_format == "text"


def test_env_example_loads_in_dev_and_is_rejected_in_prod() -> None:
    example = PROJECT_ROOT / ".env.example"
    settings = Settings(_env_file=example)
    ensure_secure(settings)
    assert settings.log_format is None
    prod = Settings(_env_file=example, app_env="prod")
    with pytest.raises(InsecureConfigError):
        ensure_secure(prod)


def test_secure_prod_config_is_accepted() -> None:
    settings = secure_prod()
    ensure_secure(settings)
    assert settings.production_problems() == []
    assert settings.effective_log_format == "json"


def test_prod_with_defaults_fails_listing_every_problem() -> None:
    with pytest.raises(InsecureConfigError) as exc:
        ensure_secure(Settings(_env_file=None, app_env="prod"))
    message = str(exc.value)
    for variable in ("APP_PASSWORD_HASH", "APP_API_KEY", "SESSION_SECRET"):
        assert variable in message


@pytest.mark.parametrize(
    ("override", "variable"),
    [
        ({"app_password_hash": ""}, "APP_PASSWORD_HASH"),
        ({"app_password_hash": "plain-text-password"}, "APP_PASSWORD_HASH"),
        ({"app_password_hash": "$argon2i$v=19$m=65536,t=3,p=4$abc$def"}, "APP_PASSWORD_HASH"),
        ({"app_api_key": "cambia-esto"}, "APP_API_KEY"),
        ({"app_api_key": "short-key"}, "APP_API_KEY"),
        ({"session_secret": ""}, "SESSION_SECRET"),
        ({"session_secret": "too-short"}, "SESSION_SECRET"),
        ({"session_secret": SECRET_KEY}, "SESSION_SECRET"),
        ({"allowed_hosts": []}, "ALLOWED_HOSTS"),
        ({"allowed_hosts": ["*"]}, "ALLOWED_HOSTS"),
        ({"cors_origins": ["*"]}, "CORS_ORIGINS"),
        ({"cors_origins": ["bets.example.com"]}, "CORS_ORIGINS"),
        ({"cors_origins": ["http://bets.example.com"]}, "CORS_ORIGINS"),
    ],
)
def test_each_insecure_value_blocks_prod(override: dict[str, Any], variable: str) -> None:
    settings = secure_prod(**override)
    with pytest.raises(InsecureConfigError) as exc:
        ensure_secure(settings)
    assert variable in str(exc.value)


def test_errors_never_print_secret_values() -> None:
    leaked = "leaky-but-short"
    settings = secure_prod(app_api_key=leaked, session_secret=leaked)
    with pytest.raises(InsecureConfigError) as exc:
        ensure_secure(settings)
    assert leaked not in str(exc.value)
    assert leaked not in repr(exc.value)


def test_secrets_are_hidden_in_repr_and_dump() -> None:
    settings = secure_prod(odds_api_key="odds-secret-123")
    text = repr(settings) + str(settings) + str(settings.model_dump())
    for secret in (SECRET_KEY, SECRET_SESSION, ARGON2_HASH, "odds-secret-123"):
        assert secret not in text
    assert settings.app_api_key.get_secret_value() == SECRET_KEY


def test_lists_are_read_comma_separated_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_HOSTS", "bets.example.com, api.example.com")
    monkeypatch.setenv("CORS_ORIGINS", "https://bets.example.com")
    settings = Settings(_env_file=None)
    assert settings.allowed_hosts == ["bets.example.com", "api.example.com"]
    assert settings.cors_origins == ["https://bets.example.com"]


def test_empty_cors_is_allowed_in_prod() -> None:
    # Same-origin deployment (frontend and API behind one proxy) needs no CORS at all.
    ensure_secure(secure_prod(cors_origins=[]))


def test_admin_key_is_a_deprecated_alias(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="betting_ml.config"):
        settings = Settings(_env_file=None, admin_api_key=SECRET_KEY)
    assert settings.app_api_key.get_secret_value() == SECRET_KEY
    assert "ADMIN_API_KEY" in caplog.text
    assert SECRET_KEY not in caplog.text


def test_old_example_admin_key_is_ignored_silently(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="betting_ml.config"):
        settings = Settings(_env_file=None, admin_api_key="cambia-esto")
    assert settings.app_api_key.get_secret_value() == "cambia-esto"
    assert caplog.text == ""


def test_app_key_wins_over_a_different_admin_key(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="betting_ml.config"):
        settings = Settings(_env_file=None, app_api_key=SECRET_KEY, admin_api_key=SECRET_SESSION)
    assert settings.app_api_key.get_secret_value() == SECRET_KEY
    assert "ADMIN_API_KEY" in caplog.text


@pytest.mark.parametrize("field", ["session_idle_minutes", "session_max_hours", "max_body_bytes"])
def test_limits_must_be_positive(field: str) -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, **{field: 0})


def test_api_refuses_to_start_in_prod_with_insecure_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from betting_ml.api.main import create_app

    insecure = Settings(_env_file=None, app_env="prod")
    monkeypatch.setattr("betting_ml.api.main.get_settings", lambda: insecure)
    built: list[bool] = []
    monkeypatch.setattr("betting_ml.container.Container.__init__", lambda *_: built.append(True))
    with pytest.raises(InsecureConfigError), TestClient(create_app()):
        pass
    assert built == []  # the check runs before anything is loaded


def test_explicit_log_format_wins_over_the_environment_default() -> None:
    assert secure_prod(log_format="text").effective_log_format == "text"
    assert Settings(_env_file=None, log_format="json").effective_log_format == "json"


@pytest.mark.parametrize(
    "weak",
    [
        "$argon2id$v=19$m=1024,t=1,p=1$c2FsdHNhbHRzYWx0$aGFzaGhhc2hoYXNoaGFzaA",
        "$argon2id$v=19$m=65536,t=1,p=4$c2FsdHNhbHRzYWx0$aGFzaGhhc2hoYXNoaGFzaA",
        "$argon2id$v=19$m=8192,t=3,p=4$c2FsdHNhbHRzYWx0$aGFzaGhhc2hoYXNoaGFzaA",
        "$argon2id$v=19$garbage",
    ],
)
def test_prod_rejects_weak_argon2_parameters(weak: str) -> None:
    """A hash made with test-grade parameters (m=1024, t=1) must not reach production."""
    problems = secure_prod(app_password_hash=weak).production_problems()
    assert any("parámetros Argon2id débiles" in p for p in problems)
    assert weak not in " ".join(problems)


def test_owasp_minimum_argon2_parameters_are_accepted() -> None:
    minimum = "$argon2id$v=19$m=19456,t=2,p=1$c2FsdHNhbHRzYWx0$aGFzaGhhc2hoYXNoaGFzaA"
    assert secure_prod(app_password_hash=minimum).production_problems() == []
