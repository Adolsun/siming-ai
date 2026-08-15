"""Regression coverage for per-data-directory desktop single-instance rules."""

import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from app.core.desktop_instance import DesktopInstanceCoordinator


class DesktopInstanceCoordinatorTestCase(unittest.TestCase):
    def test_second_instance_activates_owner_and_owner_cleanup_allows_restart(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            owner = DesktopInstanceCoordinator(home)
            follower = DesktopInstanceCoordinator(home)
            activated = threading.Event()

            self.assertTrue(owner.acquire())
            owner.start_activation_listener(
                handler=activated.set,
                metadata={"api_port": 8765, "status": "starting"},
            )
            self.assertFalse(follower.acquire())
            self.assertTrue(follower.activate_existing(timeout=1.5))
            self.assertTrue(activated.wait(1.0))

            runtime = json.loads(owner.runtime_path.read_text(encoding="utf-8"))
            self.assertEqual(runtime["api_port"], 8765)
            self.assertEqual(runtime["status"], "starting")

            follower.close()
            self.assertTrue(owner.runtime_path.exists())
            owner.close()
            self.assertFalse(owner.runtime_path.exists())

            restarted = DesktopInstanceCoordinator(home)
            self.assertTrue(restarted.acquire())
            restarted.close()

    def test_activation_received_during_boot_is_delivered_when_window_binds(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            owner = DesktopInstanceCoordinator(home)
            follower = DesktopInstanceCoordinator(home)
            activated = threading.Event()
            try:
                self.assertTrue(owner.acquire())
                owner.start_activation_listener(metadata={"status": "starting"})
                self.assertFalse(follower.acquire())
                self.assertTrue(follower.activate_existing(timeout=1.5))
                self.assertFalse(activated.is_set())

                owner.set_activation_handler(activated.set)
                self.assertTrue(activated.wait(1.0))
            finally:
                follower.close()
                owner.close()

    def test_stale_discovery_file_does_not_prevent_lock_recovery(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            runtime_path = home / "desktop-instance.json"
            runtime_path.write_text(
                json.dumps(
                    {
                        "pid": 999999,
                        "control_port": 1,
                        "token": "stale",
                    }
                ),
                encoding="utf-8",
            )

            owner = DesktopInstanceCoordinator(home)
            try:
                self.assertTrue(owner.acquire())
                owner.start_activation_listener(metadata={"status": "recovered"})
                current = json.loads(runtime_path.read_text(encoding="utf-8"))
                self.assertEqual(current["status"], "recovered")
                self.assertNotEqual(current["token"], "stale")
            finally:
                owner.close()

    def test_mutex_and_activation_work_across_real_processes(self):
        child_code = r"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, sys.argv[2])
from app.core.desktop_instance import DesktopInstanceCoordinator

activated = threading.Event()
owner = DesktopInstanceCoordinator(Path(sys.argv[1]))
if not owner.acquire():
    raise SystemExit(20)
owner.start_activation_listener(
    handler=activated.set,
    metadata={"status": "ready"},
)
result = activated.wait(8.0)
owner.close()
raise SystemExit(0 if result else 21)
"""
        backend_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            process = subprocess.Popen(
                [sys.executable, "-c", child_code, str(home), str(backend_root)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            follower = DesktopInstanceCoordinator(home)
            try:
                deadline = time.monotonic() + 5.0
                while (
                    not follower.runtime_path.exists()
                    and process.poll() is None
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.02)

                self.assertTrue(follower.runtime_path.exists())
                self.assertFalse(follower.acquire())
                self.assertTrue(follower.activate_existing(timeout=2.0))
                _, stderr = process.communicate(timeout=5.0)
                self.assertEqual(process.returncode, 0, stderr)

                restarted = DesktopInstanceCoordinator(home)
                self.assertTrue(restarted.acquire())
                restarted.close()
            finally:
                follower.close()
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=3.0)


if __name__ == "__main__":
    unittest.main()
