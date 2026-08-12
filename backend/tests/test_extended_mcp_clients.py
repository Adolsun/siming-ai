"""Tests for Kilo, Qwen Code, Hermes, and OpenClaw MCP configuration."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from app.services.external_agent.extended_clients import (
    configure_hermes,
    configure_kilocode,
    configure_openclaw,
    configure_qwen_code,
)


SERVER = {
    "command": "python.exe",
    "args": ["moshu-mcp-server.py", "--permission-pack", "auto"],
    "cwd": "D:\\Siming",
}


class ExtendedMcpClientsTest(unittest.TestCase):
    def test_kilocode_preserves_config_and_existing_permissions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            path = home / ".config" / "kilo" / "kilo.jsonc"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps({"theme": "dark", "permission": "ask", "mcp": {"other": {}}}),
                encoding="utf-8",
            )
            with patch("app.services.external_agent.extended_clients.Path.home", return_value=home):
                with patch("app.services.external_agent.extended_clients.resolve_command", return_value="kilo.cmd"):
                    result = configure_kilocode(SERVER)
            self.assertEqual(result["status"], "configured")
            config = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(config["permission"], "ask")
            self.assertEqual(config["theme"], "dark")
            self.assertIn("other", config["mcp"])
            self.assertEqual(config["mcp"]["siming"]["type"], "local")

    def test_qwen_code_preserves_approval_mode_and_does_not_auto_trust(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            path = home / ".qwen" / "settings.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"tools": {"approvalMode": "default"}}), encoding="utf-8")
            with patch("app.services.external_agent.extended_clients.Path.home", return_value=home):
                with patch("app.services.external_agent.extended_clients.resolve_command", return_value="qwen.cmd"):
                    result = configure_qwen_code(SERVER)
            self.assertEqual(result["status"], "configured")
            config = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(config["tools"]["approvalMode"], "default")
            self.assertNotIn("trust", config["mcpServers"]["siming"])
            self.assertEqual(config["mcpServers"]["siming"]["timeout"], 30000)

    def test_hermes_writes_yaml_without_dropping_existing_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.yaml"
            path.write_text("model:\n  provider: example\nhooks_auto_accept: false\n", encoding="utf-8")
            with patch.dict(os.environ, {"HERMES_HOME": temp_dir}):
                with patch("app.services.external_agent.extended_clients.hermes_command", return_value="hermes.exe"):
                    result = configure_hermes(SERVER)
            self.assertEqual(result["status"], "configured")
            config = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertEqual(config["model"]["provider"], "example")
            self.assertFalse(config["hooks_auto_accept"])
            self.assertEqual(config["mcp_servers"]["siming"]["command"], "python.exe")
            self.assertTrue(config["mcp_servers"]["siming"]["enabled"])

    def test_openclaw_uses_native_cli_without_changing_exec_policy(self):
        completed = MagicMock(returncode=0, stdout="ok", stderr="")
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            config_path = home / ".openclaw" / "openclaw.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text("{}\n", encoding="utf-8")
            with patch("app.services.external_agent.extended_clients.Path.home", return_value=home):
                with patch("app.services.external_agent.extended_clients.resolve_command", return_value="openclaw.cmd"):
                    with patch("app.services.external_agent.extended_clients.subprocess.run", return_value=completed) as run:
                        result = configure_openclaw(SERVER)
            self.assertEqual(result["status"], "configured")
            commands = [call.args[0] for call in run.call_args_list]
            self.assertTrue(any(command[:4] == ["openclaw.cmd", "mcp", "add", "siming"] for command in commands))
            add_command = next(command for command in commands if command[:4] == ["openclaw.cmd", "mcp", "add", "siming"])
            self.assertIn("--arg=moshu-mcp-server.py", add_command)
            self.assertIn("--arg=--permission-pack", add_command)
            self.assertIn("--parallel", add_command)
            self.assertFalse(any(command[:2] == ["openclaw.cmd", "setup"] for command in commands))
            self.assertFalse(any(command[:3] == ["openclaw.cmd", "exec-policy", "preset"] for command in commands))

    def test_openclaw_does_not_accept_risk_for_an_uninitialized_client(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            with patch("app.services.external_agent.extended_clients.Path.home", return_value=home):
                with patch("app.services.external_agent.extended_clients.resolve_command", return_value="openclaw.cmd"):
                    with patch("app.services.external_agent.extended_clients.subprocess.run") as run:
                        result = configure_openclaw(SERVER)

            self.assertEqual(result["status"], "error")
            self.assertIn("不会代你接受风险条款", result["detail"])
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
