"""Model-visible creation tool result projection, using the shared projector."""

import json
from dataclasses import dataclass
from typing import Any

from app.services.creation_agent_native_protocol import safe_creation_tool_result
from app.services.workspace.registry import registry
from app.services.workspace.tool_result_projection import (
    TOOL_CATEGORY_CONTROLLER_RESULT_CONTRACT,
    ToolResultOverCapacity,
    ToolResultProjectionError,
    model_tool_result_projector,
)


@dataclass(frozen=True)
class _RuntimeResultTool:
    """Explicit contract for the controller and rejected unknown tool calls."""

    name: str
    model_result_contract: Any = TOOL_CATEGORY_CONTROLLER_RESULT_CONTRACT


def creation_tool_message_content(
    name: str, result: dict[str, Any], arguments: dict[str, Any]
) -> str:
    """Apply the one declarative model-result projection path."""

    tool = registry.get(name) or _RuntimeResultTool(name=name)
    try:
        return model_tool_result_projector.project(
            tool,
            result,
            arguments=arguments,
        ).content
    except ToolResultOverCapacity as exc:
        return json.dumps(
            exc.model_error_result(),
            ensure_ascii=False,
            separators=(",", ":"),
        )
    except ToolResultProjectionError:
        return json.dumps(
            safe_creation_tool_result(
                name,
                {
                    "status": "error",
                    "data": {"reason": "model_result_projection_failed"},
                },
            ),
            ensure_ascii=False,
            separators=(",", ":"),
        )
