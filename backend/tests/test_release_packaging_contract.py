"""Release packaging must include modules loaded only by migration scripts."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_packager_includes_dynamic_database_migration_module():
    script = (ROOT / "scripts" / "build-exe.ps1").read_text(encoding="utf-8")

    assert '"--hidden-import", "app.database.migrations"' in script
    assert '"--add-data", "$(Join-Path $BackendDir \'alembic\')' in script
    assert "PackagerPythonVersion -ne $BuildPythonVersion" in script
    assert 'import tkinter' in script


def test_packager_uses_an_explicit_runtime_instead_of_the_backend_test_venv():
    script = (ROOT / "scripts" / "build-exe.ps1").read_text(encoding="utf-8")

    system_python = script.index('$Python = Get-Command "python"')
    backend_venv = script.index('$BackendPython = Join-Path $BackendDir')
    assert system_python < backend_venv
    assert "SIMING_BUILD_PYTHON" in script
    assert "Test-PackagingPython" in script
    assert "import sys,tkinter" in script
    assert '$ErrorActionPreference = "SilentlyContinue"' in script
    assert "base_executable" in script
    assert "$RuntimeChanged" in script


def test_publisher_stops_when_repository_verification_is_unavailable():
    script = (ROOT / "scripts" / "publish-github.ps1").read_text(encoding="utf-8")

    assert "gh repo create" not in script
    assert "Publishing stopped without changing repository state" in script
    assert "$ExistingTagExitCode" in script


def test_publisher_keeps_new_release_draft_until_all_assets_verify():
    script = (ROOT / "scripts" / "publish-github.ps1").read_text(encoding="utf-8")

    assert '"--draft"' in script
    assert "MissingUploadedAssets" in script
    assert "--draft=false" in script
    assert "Assert-NativeSuccess \"upload release assets" in script


def test_gateway_smokes_every_published_architecture():
    workflow = (ROOT / ".github" / "workflows" / "gateway-image.yml").read_text(encoding="utf-8")

    assert "platforms: linux/amd64" in workflow
    assert "platforms: linux/arm64" in workflow
    assert "smoke_arch amd64" in workflow
    assert "smoke_arch arm64" in workflow


def test_android_release_verifies_version_code_and_trusted_certificate():
    script = (ROOT / "scripts" / "verify-android-release.ps1").read_text(encoding="utf-8")

    assert "ExpectedCertificateSha256" in script
    assert "certificate SHA-256 digest" in script
    assert "versionCode" in script
    assert "expectedVersionCode" in script


def test_release_smoke_matches_runtime_to_update_manifest():
    script = (ROOT / "scripts" / "smoke-test-release.ps1").read_text(encoding="utf-8")

    assert '"$serverBaseUrl/health"' in script
    assert "$health.version -ne $expectedVersion" in script
