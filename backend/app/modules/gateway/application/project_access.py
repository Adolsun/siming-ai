"""Configured read port for the current shared-project grant."""

from collections.abc import Callable

_reader: Callable[[str], bool] | None = None


def configure_project_access(reader: Callable[[str], bool]) -> None:
    global _reader
    _reader = reader


def is_project_shared(project_id: str) -> bool:
    return _reader(project_id) if _reader else False
