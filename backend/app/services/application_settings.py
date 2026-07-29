"""Persistent launcher preferences shared by the API and packaged runtime."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from ..core.legacy_env import get_compatible_env
from ..updater import resolve_update_channel


def app_home() -> Path:
    configured = get_compatible_env("SIMING_HOME")
    if configured:
        return Path(configured)
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        return Path(local_app_data) / "Siming"
    return Path.home() / "Siming"


def launcher_settings_path() -> Path:
    return app_home() / "launcher-settings.json"


def load_launcher_settings() -> dict:
    path = launcher_settings_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def save_launcher_settings(settings: dict) -> None:
    path = launcher_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


_HOST_PATTERN = re.compile(
    r"^(?:\*\.)?(?:[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?|"
    r"\[[0-9A-Fa-f:]+\]|[0-9A-Fa-f:.]+)$"
)


def normalize_gateway_advertised_url(value: str | None) -> str:
    """Validate the optional public base URL without retaining credentials."""

    raw = str(value or "").strip().rstrip("/")
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("Gateway 公布地址必须是无账号、无路径的 HTTP 或 HTTPS 地址")
    hostname = parsed.hostname
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = hostname if parsed.port is None else f"{hostname}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, "", "", ""))


def normalize_gateway_allowed_hosts(value: str | None) -> str:
    """Normalize an explicit TrustedHost allowlist for the next launch."""

    raw_hosts = [item.strip().lower() for item in str(value or "").split(",")]
    hosts: list[str] = []
    for host in raw_hosts:
        if not host:
            continue
        if len(host) > 255 or not _HOST_PATTERN.fullmatch(host):
            raise ValueError(f"Gateway 允许主机格式无效：{host}")
        if host not in hosts:
            hosts.append(host)
    return ",".join(hosts)


def launcher_settings_payload() -> dict:
    settings = load_launcher_settings()
    runtime_profile = os.environ.get("SIMING_RUNTIME_PROFILE", "desktop-standalone")
    gateway_headless = runtime_profile == "gateway" and os.environ.get(
        "SIMING_GATEWAY_HEADLESS", ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    launch_mode = (
        "browser"
        if str(settings.get("launch_mode") or "").strip().lower() == "browser"
        else "desktop"
    )
    return {
        "launch_mode": launch_mode,
        "update_channel": resolve_update_channel(settings.get("update_channel")),
        "gateway_enabled": True if gateway_headless else bool(settings.get("gateway_enabled")),
        "gateway_runtime_active": (
            runtime_profile == "gateway"
        ),
        "gateway_headless": gateway_headless,
        "gateway_advertised_url": normalize_gateway_advertised_url(
            os.environ.get("SIMING_GATEWAY_ADVERTISED_URL", "")
            if gateway_headless
            else settings.get("gateway_advertised_url")
        ),
        "gateway_allowed_hosts": normalize_gateway_allowed_hosts(
            os.environ.get(
                "SIMING_GATEWAY_ALLOWED_HOSTS",
                "localhost,127.0.0.1,*.local,*.ts.net",
            )
            if gateway_headless
            else settings.get("gateway_allowed_hosts")
        ),
        "restart_required": True,
        "browser_mode_description": (
            "Use the default browser on the next launch instead of the embedded "
            "WebView2 window."
        ),
    }


__all__ = [
    "app_home",
    "launcher_settings_payload",
    "launcher_settings_path",
    "load_launcher_settings",
    "normalize_gateway_advertised_url",
    "normalize_gateway_allowed_hosts",
    "save_launcher_settings",
]
