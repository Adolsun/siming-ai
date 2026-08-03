"""Feature policy for Siming's bundled local runtime."""

from __future__ import annotations

LOCAL_RUNTIME_PROVIDER = "local_llama_cpp"


def local_runtime_enabled() -> bool:
    """The desktop local runtime is a first-class provider.

    Deployment settings (such as the Docker Gateway) decide whether it is
    available.  Desktop users must not need a hidden environment opt-in.
    """
    return True


def is_local_runtime_provider(provider: str | None) -> bool:
    return provider == LOCAL_RUNTIME_PROVIDER


def local_runtime_disabled(provider: str | None = LOCAL_RUNTIME_PROVIDER) -> bool:
    return False


def local_runtime_disabled_message() -> str:
    return "本地 AI 模型在当前部署中不可用。"
