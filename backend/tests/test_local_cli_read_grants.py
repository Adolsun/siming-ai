from __future__ import annotations

import shutil
import stat
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from app.ai import local_cli_read_grants as read_grants
from app.ai.local_cli_adapter import LocalCLIAdapter
from app.ai.local_cli_read_grants import (
    LocalCLIReadGrantError,
    normalize_explicit_read_paths,
    stage_explicit_read_paths,
)
from app.core.exceptions import LLMError


def test_explicit_file_is_copied_into_isolated_snapshot() -> None:
    with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as workspace:
        source = Path(source_dir) / "设定.md"
        source.write_text("灵气只在月圆夜恢复。", encoding="utf-8")

        attachments = stage_explicit_read_paths([str(source)], workspace)

        assert len(attachments) == 1
        manifest = Path(attachments[0])
        assert manifest.is_relative_to(Path(workspace).resolve())
        assert manifest.name == "READ_GRANT.md"
        assert str(source.resolve()) in manifest.read_text(encoding="utf-8")
        snapshots = [path for path in manifest.parent.rglob("*.md") if path != manifest]
        assert len(snapshots) == 1
        assert snapshots[0].read_text(encoding="utf-8") == "灵气只在月圆夜恢复。"


def test_directory_snapshot_is_bounded_and_skips_hidden_sensitive_files() -> None:
    with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as workspace:
        root = Path(source_dir) / "资料"
        root.mkdir()
        (root / "world.md").write_text("世界观", encoding="utf-8")
        (root / ".env").write_text("SECRET=do-not-copy", encoding="utf-8")
        hidden = root / ".git"
        hidden.mkdir()
        (hidden / "config").write_text("credential", encoding="utf-8")

        [manifest_value] = stage_explicit_read_paths([str(root)], workspace)

        manifest = Path(manifest_value)
        staged_text = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in manifest.parent.rglob("*") if path.is_file()
        )
        assert "世界观" in staged_text
        assert "do-not-copy" not in staged_text
        assert "credential" not in staged_text


@pytest.mark.parametrize("name", [".env", "id_rsa", "client.pem", "credentials.json"])
def test_sensitive_files_are_rejected(name: str) -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / name
        path.write_text("secret", encoding="utf-8")
        with pytest.raises(LocalCLIReadGrantError, match="凭据|密钥"):
            normalize_explicit_read_paths([str(path)])


def test_relative_path_is_rejected() -> None:
    with pytest.raises(LocalCLIReadGrantError, match="绝对路径"):
        normalize_explicit_read_paths(["notes/world.md"])


def test_tilde_path_is_not_treated_as_explicit_absolute_consent() -> None:
    with pytest.raises(LocalCLIReadGrantError, match="绝对路径"):
        normalize_explicit_read_paths(["~/Documents/world.md"])


def test_parent_symlink_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        target = root / "target"
        target.mkdir()
        (target / "world.md").write_text("世界观", encoding="utf-8")
        link = root / "linked"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            pytest.skip("当前 Windows 环境不允许创建测试用符号链接")

        with pytest.raises(LocalCLIReadGrantError, match="符号链接|目录联接"):
            normalize_explicit_read_paths([str(link / "world.md")])


def test_docx_with_excessive_uncompressed_size_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "oversized.docx"
        monkeypatch.setattr(read_grants, "MAX_DOCX_UNCOMPRESSED_BYTES", 64)
        with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("word/document.xml", "x" * 128)

        with pytest.raises(LocalCLIReadGrantError, match="解压后体积过大"):
            normalize_explicit_read_paths([str(path)])


def test_isolated_opencode_accepts_only_staged_manifest() -> None:
    adapter = LocalCLIAdapter(api_key="", base_url="opencode_cli", cli_command="opencode")
    with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as workspace:
        source = Path(source_dir) / "outline.txt"
        source.write_text("第一卷大纲", encoding="utf-8")

        attachments = adapter._runtime_attachments(
            {
                "local_cli_isolated": True,
                "local_cli_read_permission_granted": True,
                "local_cli_read_paths": [str(source)],
            },
            workspace,
        )

        assert len(attachments) == 1
        assert Path(attachments[0]).is_relative_to(Path(workspace).resolve())
        assert str(source.resolve()) not in attachments


def test_non_opencode_cli_cannot_use_the_path_grant_channel() -> None:
    adapter = LocalCLIAdapter(api_key="", base_url="claude_cli", cli_command="claude")
    with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as workspace:
        source = Path(source_dir) / "outline.txt"
        source.write_text("大纲", encoding="utf-8")
        with pytest.raises(LLMError, match="仅支持 OpenCode"):
            adapter._runtime_attachments(
                {
                    "local_cli_isolated": True,
                    "local_cli_read_permission_granted": True,
                    "local_cli_read_paths": [str(source)],
                },
                workspace,
            )


def test_isolated_workspace_cleanup_removes_readonly_snapshots() -> None:
    adapter = LocalCLIAdapter(api_key="", base_url="opencode_cli", cli_command="opencode")
    workspace = Path(tempfile.mkdtemp(prefix="siming-cli-isolated-"))
    snapshot = workspace / ".siming-readonly" / "source.md"
    snapshot.parent.mkdir()
    snapshot.write_text("只读快照", encoding="utf-8")
    snapshot.chmod(stat.S_IREAD)

    try:
        adapter._cleanup_isolated_workspace(str(workspace), True)
        assert not workspace.exists()
    finally:
        if workspace.exists():
            snapshot.chmod(stat.S_IWRITE | stat.S_IREAD)
            shutil.rmtree(workspace)
