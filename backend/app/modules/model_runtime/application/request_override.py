"""Request-scoped, non-persistent model configuration overrides."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from ..domain.configuration import ModelProviderConfig

_request_provider: ContextVar[ModelProviderConfig | None] = ContextVar(
    "siming_request_model_provider",
    default=None,
)


def active_request_provider() -> ModelProviderConfig | None:
    return _request_provider.get()


@contextmanager
def use_request_provider(config: ModelProviderConfig) -> Iterator[None]:
    """Activate credentials only for the current async execution context."""

    token = _request_provider.set(config)
    try:
        yield
    finally:
        _request_provider.reset(token)


__all__ = ["active_request_provider", "use_request_provider"]
