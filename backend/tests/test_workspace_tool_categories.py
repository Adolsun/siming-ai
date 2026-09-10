from app.architecture.tool_categories import (
    TOOL_CATEGORY_CONTROLLER,
    tool_category_controller_schema,
)
from app.prompts.packs.workspace_quality import PACK
from app.services.agent.prompt_builder import build_system_prompt
from app.services.workspace.tool_schemas import (
    build_workspace_tool_schemas,
    select_workspace_tool_names,
)


def test_authorized_workspace_catalog_contains_all_non_destructive_domains():
    names = select_workspace_tool_names()

    assert {
        "chapter_writer",
        "create_character",
        "detect_character_changes",
        "start_cataloging_job",
        "list_skills",
    } <= set(names)
    assert "delete_project" not in names
    assert {
        schema["function"]["name"] for schema in build_workspace_tool_schemas(names)
    } == set(names)


def test_category_projection_only_applies_authorized_category_intersection():
    writing = set(select_workspace_tool_names(["writing_context"]))
    story = set(select_workspace_tool_names(["story_knowledge"]))

    assert "chapter_writer" in writing
    assert "create_character" not in writing
    assert "create_character" in story
    assert "chapter_writer" not in story
    assert "delete_character" not in story


def test_workspace_prompt_delegates_semantics_to_model_category_selection():
    prompt = build_system_prompt(PACK, outline_batch_count=3)

    assert TOOL_CATEGORY_CONTROLLER in prompt
    assert "自行理解语义并选工具" in prompt
    assert "最新消息是唯一目标" in prompt
    assert "界面选中对象不作任务输入" in prompt
    assert "章号、标题和“下一章”须查询真实章级 ID" in prompt


def test_controller_schema_describes_categories_without_a_selection_limit():
    function = tool_category_controller_schema()["function"]
    categories = function["parameters"]["properties"]["enabled_categories"]

    assert function["name"] == TOOL_CATEGORY_CONTROLLER
    assert "maxItems" not in categories
    assert set(categories["items"]["enum"]) == {
        "project_files",
        "story_knowledge",
        "writing_context",
        "cataloging",
        "analysis_governance",
        "creation_data",
        "creation_flow",
        "agent_runtime",
        "extensions",
    }
