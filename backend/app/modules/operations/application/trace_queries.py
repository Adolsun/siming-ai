"""Configured diagnostic query port."""

from __future__ import annotations

from typing import Any

_queries: Any = None


def configure_trace_queries(queries: Any) -> None:
    global _queries
    _queries = queries


def get_trace_queries():
    return _queries
