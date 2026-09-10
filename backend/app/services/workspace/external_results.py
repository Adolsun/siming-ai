"""Consistent failure envelopes for external writing and cataloging tools."""
from typing import Any


def external_tool_failure(
    tool: str, detail: str, data: Any = None, *, status: str = "skipped",
) -> dict[str, Any]:
    return {"tool": tool, "status": status, "detail": detail, "data": data}
