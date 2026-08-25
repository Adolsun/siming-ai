"""Verified OpenCode releases used by Siming's managed Windows installer."""
from __future__ import annotations

import ctypes
import os
import platform
from typing import Any

PINNED_OPENCODE_VERSION = "v1.18.4"
_GITHUB_RELEASE_ROOT = (
    "https://github.com/anomalyco/opencode/releases/download/"
    f"{PINNED_OPENCODE_VERSION}"
)
_WINDOWS_ASSETS: dict[str, tuple[int, str]] = {
    "opencode-windows-arm64.zip": (
        57_547_484,
        "4b4d2b48afdf1432a697bccabe230c3d614cf8ed34f5bc0acf9ffd89bb9cfb25",
    ),
    "opencode-windows-x64-baseline.zip": (
        59_388_430,
        "3bfb70c41d0278221d1fbc58efe77f79615491252498ff3f5a82db64266234e0",
    ),
    "opencode-windows-x64.zip": (
        59_388_435,
        "814dae5724dfa396a43b6408703d0929625483e2fac135623f10f0fa8db04a96",
    ),
}

# OpenCode publishes the same versioned Windows executables as platform npm
# packages.  Keeping their immutable npm integrity and compressed size here lets
# onboarding use npm (and a byte-identical npm mirror) as independent download
# paths without trusting either transport for integrity.
_WINDOWS_NPM_ASSETS: dict[str, tuple[str, int, str]] = {
    "opencode-windows-arm64.zip": (
        "opencode-windows-arm64",
        57_153_278,
        "07a9bb37b64f8ff13ac71d596928cd5b48074ddd1bdcd4d27fd99088ddd6f3dc"
        "e38b7a07f553872d076b3f5d2b01dff6b99e59b6dc52911aa3fe2c20016fb74d",
    ),
    "opencode-windows-x64-baseline.zip": (
        "opencode-windows-x64-baseline",
        58_837_235,
        "e04a59f7bb88e74bd5bfd513e6c0de2b77dffac173aa66c14f84cd1a4305f6e"
        "c0d4ca258aa8495b8e2198487cb4cb365ac42b685ddbfb1fff819084890cea24f",
    ),
    "opencode-windows-x64.zip": (
        "opencode-windows-x64",
        58_837_212,
        "4ee98e70c3af67abdfb37e3c2e018b2bd7851012ec87ec08fd45e643c0615d6f"
        "79615d56776e93bad4b3422e0bff02dfb6c0df97c43a6ca436b6b5ad181cc1bd",
    ),
}


def windows_supports_avx2() -> bool:
    """Match OpenCode's Windows installer feature check, preferring baseline on doubt."""
    if os.name != "nt":
        return False
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        probe = kernel32.IsProcessorFeaturePresent
        probe.argtypes = [ctypes.c_uint]
        probe.restype = ctypes.c_bool
        return bool(probe(40))
    except (AttributeError, OSError, TypeError):
        return False


def windows_asset_name(
    *,
    machine: str | None = None,
    avx2_supported: bool | None = None,
) -> str:
    architecture = (machine or platform.machine()).lower()
    if architecture in {"arm64", "aarch64"}:
        return "opencode-windows-arm64.zip"
    if architecture not in {"amd64", "x86_64"}:
        detected = machine or platform.machine() or "unknown"
        raise RuntimeError(f"暂不支持当前 Windows 架构：{detected}")
    supports_avx2 = windows_supports_avx2() if avx2_supported is None else avx2_supported
    suffix = "" if supports_avx2 else "-baseline"
    return f"opencode-windows-x64{suffix}.zip"


def managed_windows_release(
    *,
    machine: str | None = None,
    avx2_supported: bool | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return a release whose URL and digest were verified when Siming was built."""
    asset_name = windows_asset_name(
        machine=machine,
        avx2_supported=avx2_supported,
    )
    size, sha256 = _WINDOWS_ASSETS[asset_name]
    npm_package, npm_size, npm_sha512 = _WINDOWS_NPM_ASSETS[asset_name]
    npm_version = PINNED_OPENCODE_VERSION.removeprefix("v")
    npm_path = f"{npm_package}/-/{npm_package}-{npm_version}.tgz"
    github_url = f"{_GITHUB_RELEASE_ROOT}/{asset_name}"
    return PINNED_OPENCODE_VERSION, {
        "name": asset_name,
        "size": size,
        "digest": f"sha256:{sha256}",
        "browser_download_url": github_url,
        "download_sources": [
            {
                "label": "GitHub 官方源",
                "url": github_url,
                "archive_format": "zip",
                "size": size,
                "digest": f"sha256:{sha256}",
            },
            {
                "label": "npm 官方源",
                "url": f"https://registry.npmjs.org/{npm_path}",
                "archive_format": "tgz",
                "size": npm_size,
                "digest": f"sha512:{npm_sha512}",
            },
            {
                "label": "国内加速源",
                "url": f"https://registry.npmmirror.com/{npm_path}",
                "archive_format": "tgz",
                "size": npm_size,
                "digest": f"sha512:{npm_sha512}",
            },
        ],
    }
