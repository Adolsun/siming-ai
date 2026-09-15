"""PC/Android use the same durable evidence to restore imported chapter gates."""

import json
from pathlib import Path

import pytest

from app.services.project_package_chapter_state import ProjectPackageChapterCatalogingState

CASES = json.loads((Path(__file__).resolve().parents[2] / "contracts" / "fixtures" /
                    "project-package-v1-chapter-state.json").read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_shared_project_package_chapter_state(case):
    state = ProjectPackageChapterCatalogingState(case["snapshots"], case["summaries"])
    assert state.required(case["chapter"]) is case["required"]
