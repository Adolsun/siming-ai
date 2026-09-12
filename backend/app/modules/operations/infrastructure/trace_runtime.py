"""Composition and lifetime of the optional local diagnostics store."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.engine import make_url

from ..application.trace_capture import configure_trace_sink
from ..application.trace_queries import configure_trace_queries
from .trace_queries import TraceQueries
from .trace_store import TraceStore

_store: TraceStore | None = None


def start_trace_store(database_url: str) -> None:
    global _store
    if _store is not None:
        return
    database = make_url(database_url).database
    if not database or database == ":memory:":
        return
    try:
        _store = TraceStore(
            Path(database).resolve().parent / "diagnostics" / "context-traces.sqlite3"
        )
        configure_trace_sink(_store)
        configure_trace_queries(TraceQueries(_store))
    except Exception:
        configure_trace_sink(None)


def get_trace_store() -> TraceStore | None:
    return _store


def stop_trace_store() -> None:
    global _store
    configure_trace_sink(None)
    configure_trace_queries(None)
    if _store:
        _store.close()
        _store = None
