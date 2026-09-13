"""Configured diagnostic query port exposed to HTTP interfaces."""

from ..application.trace_queries import get_trace_queries

__all__ = ["get_trace_queries"]
