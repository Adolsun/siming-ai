"""Diagnostic reads enforce device ownership and current shared-project access."""

from __future__ import annotations

import hashlib
import json
import tempfile
import zipfile
from pathlib import Path

from ..domain.context_trace import TRACE_SCHEMA
from .trace_payload import redact
from .trace_store import TraceStore


class TraceQueries:
    def __init__(self, store: TraceStore) -> None:
        self.store = store

    @staticmethod
    def _scope_available(owner: str, item: dict) -> bool:
        if owner == "local" or item["scope_kind"] != "project_conversation":
            return True
        from app.modules.gateway.interfaces.project_access import is_project_shared

        return is_project_shared(item["scope_id"])

    def trace(self, owner: str, trace_id: str) -> dict | None:
        item = self.store.trace(owner, trace_id)
        return item if item and self._scope_available(owner, item) else None

    def list_traces(self, owner: str, query) -> dict:
        items = self.store.list_traces(
            owner,
            query.scope.kind if query.scope else None,
            query.scope.id if query.scope else None,
            query.correlation_id,
            query.before,
            query.limit,
        )
        return {
            "items": [item for item in items if self._scope_available(owner, item)],
            "next_cursor": items[-1]["cursor"] if len(items) == query.limit else None,
        }

    def export(self, owner: str, trace_id: str) -> Path:
        trace = self.trace(owner, trace_id)
        if not trace:
            raise KeyError(trace_id)
        with tempfile.NamedTemporaryFile(
            prefix="siming-trace-", suffix=".zip", delete=False
        ) as handle:
            path = Path(handle.name)
        try:
            # The reader lock prevents cleanup/retention from deleting pages mid-export.
            # Business calls only enqueue diagnostics and never wait for this lock.
            with self.store.lock:
                trace = self.trace(owner, trace_id)
                if not trace or trace["finished"] is None:
                    raise ValueError("任务尚未结束或记录已清理，请刷新后导出。")
                self._write_export(path, owner, trace)
            return path
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    def _write_export(self, path: Path, owner: str, trace: dict) -> None:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            from app.version import APP_VERSION

            files = []
            digest, event_bytes = hashlib.sha256(), 0
            with archive.open("events.jsonl", "w") as stream:
                after = 0
                while events := self.store.events(owner, trace["id"], after, 100):
                    for event in events:
                        raw = (json.dumps(redact(event), ensure_ascii=False) + "\n").encode()
                        stream.write(raw)
                        digest.update(raw)
                        event_bytes += len(raw)
                    after = events[-1]["sequence"]
            files.append(
                {"path": "events.jsonl", "bytes": event_bytes, "sha256": digest.hexdigest()}
            )
            after = 0
            while events := self.store.events(owner, trace["id"], after, 100):
                for event in events:
                    item = self._export_payload(archive, owner, trace["id"], event)
                    if item:
                        files.append(item)
                after = events[-1]["sequence"]
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "schema": TRACE_SCHEMA,
                        "application_version": APP_VERSION,
                        "trace": redact(trace),
                        "contains_creative_content": trace["mode"] == "full",
                        "capture_status": trace["capture_status"],
                        "files": files,
                    },
                    ensure_ascii=False,
                ),
            )

    def _export_payload(self, archive, owner: str, trace_id: str, event: dict) -> dict | None:
        if not event["data"].get("content_hash"):
            return
        payload_id, offset = event["event_id"], 0
        chunks = []
        while part := self.store.payload(owner, trace_id, payload_id, offset):
            chunks.append(part["content"])
            offset += len(part["content"])
            if offset >= part["total_characters"]:
                break
        raw = json.dumps(
            redact(json.loads("".join(chunks))), ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        name = f"payloads/{payload_id}.json"
        archive.writestr(name, raw)
        return {"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
