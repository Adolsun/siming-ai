"""Export cataloging PromptSpecs from the same rules used by the native worker."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.prompts.cataloging_source import (  # noqa: E402
    get_internal_cataloging_system_prompt, get_project_binding_rules, get_external_no_api_rules,
)


def export() -> None:
    for name, body in (
        ("cataloging-candidates.md", get_internal_cataloging_system_prompt()),
        ("cataloging-external.md", get_project_binding_rules() + "\n\n" + get_external_no_api_rules()),
    ):
        path = ROOT / "backend/prompt_specs/continuity" / name
        header = path.read_text(encoding="utf-8").split("---", 2)[1]
        path.write_text("---" + header + "---\n" + body + "\n", encoding="utf-8")


if __name__ == "__main__":
    export()
