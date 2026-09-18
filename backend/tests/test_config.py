"""Tests for app.config — specifically the never_echo_in_production validator."""

import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError


def _make_settings(**overrides):
    """Construct a Settings instance with env vars overridden.

    Uses a patched environment so the real .env file and system env vars
    don't interfere.  Every setting needed for a valid Settings object is
    given a safe default; the caller overrides what they want to test.
    """
    env = {
        "GROQ_API_KEY": "",
        "DATABASE_URL": "sqlite+aiosqlite:///./test.db",
        "UPLOAD_DIR": "./uploads",
        "APP_ENV": "development",
        "SQL_ECHO": "false",
        "CORS_ORIGINS": "http://localhost:5173",
    }
    env.update({k.upper(): str(v) for k, v in overrides.items()})

    with patch.dict(os.environ, env, clear=False):
        # Import inside the function so the lru_cache on get_settings()
        # doesn't interfere — we construct Settings directly.
        from app.config import Settings

        return Settings(
            _env_file=None,  # ignore the real .env
            **{k.lower(): v for k, v in overrides.items()},
        )


class TestNeverEchoInProduction:
    """The validator must refuse to boot when sql_echo=True + app_env=production."""

    def test_production_with_echo_raises(self):
        with pytest.raises(ValidationError, match="sql_echo must not be enabled in production"):
            _make_settings(app_env="production", sql_echo=True)

    def test_production_without_echo_ok(self):
        s = _make_settings(app_env="production", sql_echo=False)
        assert s.app_env == "production"
        assert s.sql_echo is False

    def test_development_with_echo_ok(self):
        s = _make_settings(app_env="development", sql_echo=True)
        assert s.sql_echo is True

    def test_development_without_echo_ok(self):
        s = _make_settings(app_env="development", sql_echo=False)
        assert s.sql_echo is False

    def test_default_sql_echo_is_false(self):
        s = _make_settings(app_env="development")
        assert s.sql_echo is False
