"""Desktop single-instance discovery and activation.

The desktop application is single-instance per Siming data directory.  A
process-wide mutex/file lock owns the instance, while a small authenticated
loopback socket lets later launches bring the existing window to the front.
"""

from __future__ import annotations

import contextlib
import ctypes
import hashlib
import json
import os
import secrets
import socket
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

ActivationHandler = Callable[[], None]


class DesktopInstanceCoordinator:
    """Coordinate one desktop process for a particular application home."""

    _RUNTIME_FILENAME = "desktop-instance.json"
    _LOCK_FILENAME = "desktop-instance.lock"
    _ERROR_ALREADY_EXISTS = 183

    def __init__(self, app_home: Path, *, app_name: str = "Siming") -> None:
        self.app_home = Path(app_home).expanduser().resolve()
        self.app_name = app_name
        self.runtime_path = self.app_home / self._RUNTIME_FILENAME
        self.lock_path = self.app_home / self._LOCK_FILENAME

        normalized_home = os.path.normcase(str(self.app_home))
        identity = hashlib.sha256(normalized_home.encode("utf-8")).hexdigest()[:24]
        self._mutex_name = f"Local\\{app_name}-desktop-{identity}"

        self._is_owner = False
        self._closed = False
        self._mutex_handle: int | None = None
        self._lock_file: Any | None = None
        self._listener: socket.socket | None = None
        self._listener_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._state_lock = threading.Lock()
        self._activation_handler: ActivationHandler | None = None
        self._activation_pending = False
        self._token = ""
        self._started_at = 0.0
        self._metadata: dict[str, Any] = {}

    @property
    def is_owner(self) -> bool:
        return self._is_owner

    def acquire(self) -> bool:
        """Acquire ownership, returning ``False`` when another instance owns it."""

        if self._closed:
            raise RuntimeError("Desktop instance coordinator is already closed")
        if self._is_owner:
            return True

        self.app_home.mkdir(parents=True, exist_ok=True)
        acquired = (
            self._acquire_windows_mutex()
            if os.name == "nt"
            else self._acquire_file_lock()
        )

        self._is_owner = acquired
        return acquired

    def _acquire_windows_mutex(self) -> bool:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_mutex = kernel32.CreateMutexW
        create_mutex.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        create_mutex.restype = ctypes.c_void_p

        ctypes.set_last_error(0)
        handle = create_mutex(None, False, self._mutex_name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())

        if ctypes.get_last_error() == self._ERROR_ALREADY_EXISTS:
            close_handle = kernel32.CloseHandle
            close_handle.argtypes = [ctypes.c_void_p]
            close_handle.restype = ctypes.c_bool
            close_handle(handle)
            return False

        self._mutex_handle = int(handle)
        return True

    def _acquire_file_lock(self) -> bool:
        import fcntl

        lock_file = self.lock_path.open("a+b")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock_file.close()
            return False
        self._lock_file = lock_file
        return True

    def start_activation_listener(
        self,
        *,
        handler: ActivationHandler | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Publish discovery metadata and accept activation requests."""

        if not self._is_owner:
            raise RuntimeError("Only the owning desktop instance can publish itself")
        if self._listener is not None:
            if handler is not None:
                self.set_activation_handler(handler)
            if metadata:
                self.update_metadata(**metadata)
            return

        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(4)
        listener.settimeout(0.25)

        self._listener = listener
        self._token = secrets.token_urlsafe(32)
        self._started_at = time.time()
        self._activation_handler = handler
        self._metadata = dict(metadata or {})
        self._listener_thread = threading.Thread(
            target=self._listen_for_activation,
            name="siming-instance-activation",
            daemon=True,
        )
        self._listener_thread.start()
        self._write_runtime_file()

    def set_activation_handler(self, handler: ActivationHandler) -> None:
        should_dispatch = False
        with self._state_lock:
            self._activation_handler = handler
            if self._activation_pending:
                self._activation_pending = False
                should_dispatch = True
        if should_dispatch:
            threading.Thread(
                target=self._run_handler,
                name="siming-instance-activate-pending",
                daemon=True,
            ).start()

    def update_metadata(self, **metadata: Any) -> None:
        if not self._is_owner or self._listener is None:
            return
        with self._state_lock:
            self._metadata.update(metadata)
        self._write_runtime_file()

    def activate_existing(self, *, timeout: float = 3.0) -> bool:
        """Ask the current owner to surface its window/browser."""

        deadline = time.monotonic() + max(timeout, 0.1)
        while time.monotonic() < deadline:
            info = self._read_runtime_file()
            if info:
                try:
                    control_port = int(info["control_port"])
                    token = str(info["token"])
                    request = json.dumps(
                        {"action": "activate", "token": token},
                        ensure_ascii=False,
                    ).encode("utf-8") + b"\n"
                    with socket.create_connection(
                        ("127.0.0.1", control_port), timeout=0.6
                    ) as connection:
                        connection.sendall(request)
                        connection.settimeout(0.6)
                        response = connection.recv(512)
                    if response:
                        payload = json.loads(response.decode("utf-8"))
                        return payload.get("status") == "ok"
                except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
                    pass
            time.sleep(0.08)
        return False

    def _listen_for_activation(self) -> None:
        listener = self._listener
        if listener is None:
            return
        while not self._stop_event.is_set():
            try:
                connection, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                break

            with connection:
                try:
                    connection.settimeout(1.0)
                    raw = self._receive_line(connection)
                    request = json.loads(raw.decode("utf-8"))
                    if (
                        request.get("action") != "activate"
                        or not secrets.compare_digest(
                            str(request.get("token", "")), self._token
                        )
                    ):
                        connection.sendall(b'{"status":"denied"}\n')
                        continue
                    self._dispatch_activation()
                    connection.sendall(b'{"status":"ok"}\n')
                except (OSError, ValueError, json.JSONDecodeError):
                    with contextlib.suppress(OSError):
                        connection.sendall(b'{"status":"error"}\n')

    @staticmethod
    def _receive_line(connection: socket.socket, *, limit: int = 4096) -> bytes:
        chunks = bytearray()
        while len(chunks) < limit:
            chunk = connection.recv(min(512, limit - len(chunks)))
            if not chunk:
                break
            chunks.extend(chunk)
            if b"\n" in chunk:
                break
        if not chunks:
            raise ValueError("Empty activation request")
        return bytes(chunks).split(b"\n", 1)[0]

    def _dispatch_activation(self) -> None:
        with self._state_lock:
            handler = self._activation_handler
            if handler is None:
                self._activation_pending = True
                return
        self._run_handler()

    def _run_handler(self) -> None:
        with self._state_lock:
            handler = self._activation_handler
        if handler is None:
            return
        try:
            handler()
        except Exception:
            # Activation must never take down the owning desktop process.
            return

    def _runtime_payload(self) -> dict[str, Any]:
        listener = self._listener
        if listener is None:
            raise RuntimeError("Activation listener has not been started")
        with self._state_lock:
            metadata = dict(self._metadata)
        return {
            "schema_version": 1,
            "pid": os.getpid(),
            "control_port": int(listener.getsockname()[1]),
            "token": self._token,
            "started_at": self._started_at,
            "app_home": str(self.app_home),
            **metadata,
        }

    def _write_runtime_file(self) -> None:
        payload = self._runtime_payload()
        temp_path = self.runtime_path.with_name(
            f"{self.runtime_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        try:
            temp_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temp_path, self.runtime_path)
        finally:
            with contextlib.suppress(OSError):
                temp_path.unlink(missing_ok=True)

    def _read_runtime_file(self) -> dict[str, Any] | None:
        try:
            payload = json.loads(self.runtime_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop_event.set()

        listener = self._listener
        self._listener = None
        if listener is not None:
            with contextlib.suppress(OSError):
                listener.close()
        listener_thread = self._listener_thread
        if listener_thread and listener_thread.is_alive():
            listener_thread.join(timeout=1.0)

        if self._is_owner:
            info = self._read_runtime_file()
            if info and info.get("token") == self._token:
                with contextlib.suppress(OSError):
                    self.runtime_path.unlink(missing_ok=True)

        if self._mutex_handle is not None and os.name == "nt":
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            close_handle = kernel32.CloseHandle
            close_handle.argtypes = [ctypes.c_void_p]
            close_handle.restype = ctypes.c_bool
            close_handle(ctypes.c_void_p(self._mutex_handle))
            self._mutex_handle = None

        if self._lock_file is not None:
            try:
                if os.name != "nt":
                    import fcntl

                    fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
            finally:
                self._lock_file.close()
                self._lock_file = None

        self._is_owner = False

    def __enter__(self) -> DesktopInstanceCoordinator:
        self.acquire()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()


__all__ = ["DesktopInstanceCoordinator"]
