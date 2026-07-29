"""Legacy gateway adapter for the model execution application port."""
from __future__ import annotations

from typing import Any

from app.ai.local_cli_adapter import is_local_cli_provider
from app.core.exceptions import ValidationError

from .gateway import LLMGateway


class GatewayModelExecutor:
    async def chat_completion(self, **kwargs: Any) -> Any:
        return await LLMGateway.chat_completion(**kwargs)

    def stream_chat_completion(self, **kwargs: Any):
        return LLMGateway.stream_chat_completion(**kwargs)

    def stream_chat_completion_with_tools(self, **kwargs: Any):
        return LLMGateway.stream_chat_completion_with_tools(**kwargs)

    def supports_tool_calling(self, model: str | None = None) -> bool:
        return LLMGateway.supports_tool_calling(model)

    def local_cli_extra_body(self, model: str | None = None, **kwargs: Any) -> dict | None:
        return LLMGateway.local_cli_extra_body(model, **kwargs)

    def select_model_for_task(self, **kwargs: Any):
        return LLMGateway.select_model_for_task(**kwargs)

    def model_identity(
        self, model: str | None = None, extra_body: dict | None = None
    ) -> tuple[str, str]:
        return LLMGateway.model_identity(model, extra_body)

    def provider_for_model(self, model: str | None = None) -> str:
        return LLMGateway.provider_for_model(model)


class CloudOnlyGatewayModelExecutor(GatewayModelExecutor):
    """Model executor for the container runtime, where local processes do not exist."""

    @staticmethod
    def _require_cloud(model: str | None = None) -> None:
        provider = LLMGateway.provider_for_model(model)
        if provider == "local_llama_cpp" or is_local_cli_provider(provider):
            raise ValidationError(
                "Docker Gateway 仅支持云端 API 模型；本地模型与 CLI 仍留在桌面端。"
            )

    async def chat_completion(self, **kwargs: Any) -> Any:
        self._require_cloud(kwargs.get("model"))
        return await super().chat_completion(**kwargs)

    def stream_chat_completion(self, **kwargs: Any):
        self._require_cloud(kwargs.get("model"))
        return super().stream_chat_completion(**kwargs)

    def stream_chat_completion_with_tools(self, **kwargs: Any):
        self._require_cloud(kwargs.get("model"))
        return super().stream_chat_completion_with_tools(**kwargs)

    def supports_tool_calling(self, model: str | None = None) -> bool:
        self._require_cloud(model)
        return super().supports_tool_calling(model)

    def local_cli_extra_body(self, model: str | None = None, **kwargs: Any) -> dict | None:
        self._require_cloud(model)
        return None

    def select_model_for_task(self, **kwargs: Any):
        selection = super().select_model_for_task(**kwargs)
        self._require_cloud(selection.model)
        return selection

    def provider_for_model(self, model: str | None = None) -> str:
        self._require_cloud(model)
        return super().provider_for_model(model)


__all__ = ["CloudOnlyGatewayModelExecutor", "GatewayModelExecutor"]
