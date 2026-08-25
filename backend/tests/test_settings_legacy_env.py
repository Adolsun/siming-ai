"""Regression tests for desktop configuration upgrades."""
from __future__ import annotations

import sys

from app.core.config import Settings, get_settings


def test_deprecated_desktop_env_keys_do_not_block_startup(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "DATABASE_URL=sqlite:///./upgrade-test.db",
                "TERMINAL_MODAL_IMAGE=nikolaik/python-nodejs:python3.11-nodejs20",
                "TERMINAL_TIMEOUT=60",
                "TERMINAL_LIFETIME_SECONDS=300",
                "BROWSERBASE_PROXIES=true",
                "BROWSERBASE_ADVANCED_STEALTH=false",
                "BROWSER_SESSION_TIMEOUT=300",
                "BROWSER_INACTIVITY_TIMEOUT=120",
                "WEB_TOOLS_DEBUG=false",
                "VISION_TOOLS_DEBUG=false",
                "MOA_TOOLS_DEBUG=false",
                "IMAGE_TOOLS_DEBUG=false",
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.database_url == "sqlite:///./upgrade-test.db"


def test_packaged_settings_do_not_read_callers_dotenv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SIMING_RUNTIME_PROFILE", raising=False)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "DATABASE_URL=sqlite:///./foreign-agent.db",
                "SIMING_RUNTIME_PROFILE=foreign-agent-value",
                "TERMINAL_TIMEOUT=60",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    get_settings.cache_clear()

    try:
        settings = get_settings()
    finally:
        get_settings.cache_clear()

    assert settings.database_url == "sqlite:///./novel_agent.db"
    assert settings.runtime_profile == "desktop-standalone"


def test_source_settings_still_support_project_dotenv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SIMING_RUNTIME_PROFILE", raising=False)
    (tmp_path / ".env").write_text(
        "DATABASE_URL=sqlite:///./source-development.db\nTERMINAL_TIMEOUT=60\n",
        encoding="utf-8",
    )
    monkeypatch.delattr(sys, "frozen", raising=False)
    get_settings.cache_clear()

    try:
        settings = get_settings()
    finally:
        get_settings.cache_clear()

    assert settings.database_url == "sqlite:///./source-development.db"
