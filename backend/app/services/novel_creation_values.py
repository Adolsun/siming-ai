"""Small value parsers shared by creation services without service cycles."""
from __future__ import annotations

import re
from typing import Any

from app.core.numbers import chinese_number_to_int


def requested_volume_count(draft: dict[str, Any]) -> int | None:
    """Read the author's latest explicit volume-count requirement."""
    requirements = draft.get("locked_requirements")
    source = "\n".join([
        str(draft.get("author_outline") or "").strip(),
        *[
            str(item or "").strip()
            for item in (requirements if isinstance(requirements, list) else [])
        ],
    ])
    matches = re.findall(r"([0-9０-９零〇一二两三四五六七八九十百]+)\s*卷", source)
    if not matches:
        return None
    token = matches[-1].translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    value = int(token) if token.isdigit() else chinese_number_to_int(token)
    return value if value is not None and 1 <= value <= 100 else None
