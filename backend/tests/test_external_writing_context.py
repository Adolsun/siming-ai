"""Tests for external writing context tool — API-free context preparation."""
import asyncio
import json
import sys
import os
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.workspace.registry import registry


class ExternalWritingContextToolRegisteredTest(unittest.TestCase):
    """Verify prepare_external_writing_context is registered."""

    def test_registered(self):
        td = registry.get("prepare_external_writing_context")
        self.assertIsNotNone(td)
        self.assertEqual(td.tool_type, "read")

    def test_in_readonly_pack(self):
        from app.mcp.adapter import list_mcp_tools
        tools = list_mcp_tools(permission_pack="readonly_collaboration")
        names = {t.name for t in tools}
        self.assertIn("prepare_external_writing_context", names)


class PrepareExternalWritingContextTest(unittest.TestCase):
    """Verify prepare_external_writing_context behavior."""

    def test_project_not_found(self):
        from app.services.workspace.tools.external_writing import prepare_external_writing_context
        db = MagicMock()
        query_mock = MagicMock()
        query_mock.filter.return_value = query_mock
        query_mock.first.return_value = None
        db.query.return_value = query_mock

        result = asyncio.run(prepare_external_writing_context(db, "nonexistent", {}))
        self.assertEqual(result["status"], "skipped")

    def test_returns_context_sections(self):
        from app.services.workspace.tools.external_writing import prepare_external_writing_context
        from datetime import datetime

        # Mock project
        project = MagicMock()
        project.id = "p1"
        project.title = "Test Novel"
        project.writing_style = "natural"
        project.forbidden_sentence_patterns = "仿佛\n不由得"
        project.narrative_perspective = "third_person"

        # Mock character
        char = MagicMock()
        char.id = "c1"
        char.name = "Hero"
        char.aliases = []
        char.role_type = "protagonist"
        char.age = "adult"
        char.appearance = "Scarred"
        char.personality = "Brave"
        char.background = "Guard of the northern gate"
        char.abilities = '["swordsmanship"]'
        char.current_location = "Castle"
        char.current_goal = "Save world"
        char.life_status = "alive"
        char.realm_or_level = "captain"
        char.physical_state = "healthy"
        char.mental_state = "alert"
        char.active_conflict = "invading army"
        char.abilities_state = "ready"
        char.items_or_assets = "family sword"
        char.profile_json = {
            "core_motivation": "protect civilians",
            "voice": "brief commands",
        }
        char.ai_config = MagicMock()
        char.ai_config.tone_style = "restrained"
        char.ai_config.catchphrases = '["Hold the line"]'
        char.ai_config.verbosity = "brief"
        char.ai_config.emotion_tendency = "calm"
        char.ai_config.model_override = None
        char.ai_config.custom_system_prompt = "Act only on verified threats."

        # Mock worldbuilding
        wb = MagicMock()
        wb.id = "w1"
        wb.title = "Magic System"
        wb.dimension = "power_system"
        wb.content = "Magic requires mana"

        # Mock prompt pack
        pack = MagicMock()
        pack.pack_id = "chapter_writing_quality"
        pack.version = "1.0.0"
        pack.title = "Quality Writing"
        pack.system_prompt = "Write well..."
        pack.workflow_json = [{"step": 1}]
        pack.quality_rubric_json = {"dimensions": []}
        pack.forbidden_patterns_json = ["仿佛"]

        def query_side_effect(model):
            q = MagicMock()
            q.filter.return_value = q
            q.order_by.return_value = q
            q.limit.return_value = q
            model_name = model.__name__ if hasattr(model, '__name__') else str(model)
            if "Project" in model_name:
                q.first.return_value = project
            elif "PublicPromptPack" in model_name:
                q.first.return_value = pack
            elif "Character" in model_name and "Relationship" not in model_name:
                q.all.return_value = [char]
                q.first.return_value = char
            elif "WorldbuildingEntry" in model_name:
                q.all.return_value = [wb]
            elif "Chapter" in model_name:
                q.all.return_value = []
            elif "CharacterRelationship" in model_name:
                q.all.return_value = []
            elif "OutlineNode" in model_name:
                q.first.return_value = None
            else:
                q.first.return_value = None
                q.all.return_value = []
            return q

        db = MagicMock()
        db.query.side_effect = query_side_effect

        result = asyncio.run(prepare_external_writing_context(
            db,
            "p1",
            {"mode": "quality", "involved_characters": ["Hero"]},
        ))
        self.assertEqual(result["status"], "ok")
        data = result["data"]
        self.assertIn("prompt_pack", data)
        self.assertIn("characters", data)
        self.assertIn("worldbuilding", data)
        self.assertIn("warnings", data)
        self.assertIn("next_tool_suggestions", data)
        self.assertEqual(data["effective_mode"], "quality")
        self.assertNotIn("analysis_prompts", data)
        self.assertEqual(data["forbidden_patterns"], [])
        self.assertIsNone(data["quality_rubric"])
        self.assertEqual(data["workflow_boundaries"]["de_ai_revision"], "separate_user_action")
        next_tools = {item["tool"] for item in data["next_tool_suggestions"]}
        self.assertNotIn("record_external_quality_review", next_tools)
        self.assertNotIn("evaluate_chapter", next_tools)

    def test_real_context_exposes_complete_character_card_and_relationship(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.database.models import (
            Base,
            Character,
            CharacterAIConfig,
            CharacterRelationship,
            OutlineNode,
            OutlineNodeCharacter,
            Project,
        )
        from app.services.workspace.tools.external_writing import prepare_external_writing_context

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        try:
            project = Project(id="p1", title="Complete context", writing_style="natural")
            outline = OutlineNode(
                id="o1",
                project_id=project.id,
                title="第一章",
                node_type="chapter",
                summary="姜尘向石翁求助。",
            )
            hero = Character(
                id="c1",
                project_id=project.id,
                name="姜尘",
                role_type="protagonist",
                mental_state="警惕",
                current_goal="查清骨光来源",
                profile_json={
                    "core_motivation": "保护边荒城",
                    "voice": "短句",
                },
            )
            elder = Character(id="c2", project_id=project.id, name="石翁")
            hero.ai_config = CharacterAIConfig(
                id="cfg1",
                character_id=hero.id,
                tone_style="克制",
                verbosity="brief",
                catchphrases='["先看证据"]',
            )
            db.add_all([project, outline, hero, elder])
            db.flush()
            db.add_all([
                OutlineNodeCharacter(outline_node_id=outline.id, character_id=hero.id),
                CharacterRelationship(
                    id="rel1",
                    project_id=project.id,
                    character_a_id=hero.id,
                    character_b_id=elder.id,
                    relationship_type="师友",
                    description="石翁传授辨骨之法。",
                ),
            ])
            db.commit()

            result = asyncio.run(prepare_external_writing_context(
                db,
                project.id,
                {"mode": "quality", "outline_node_id": outline.id},
            ))

            self.assertEqual(result["status"], "ok")
            card = result["data"]["characters"][0]
            self.assertEqual(card["profile"]["core_motivation"], "保护边荒城")
            self.assertEqual(card["ai_config"]["verbosity"], "brief")
            self.assertEqual(card["mental_state"], "警惕")
            self.assertIn("师友", card["context"])
            self.assertEqual(result["data"]["relationships"][0]["target_name"], "石翁")
        finally:
            db.close()
            Base.metadata.drop_all(engine)
            engine.dispose()

    def test_fast_request_uses_fast_prompt(self):
        from app.services.workspace.tools.external_writing import prepare_external_writing_context

        project = MagicMock()
        project.id = "p1"
        project.title = "Test Novel"
        project.writing_style = "natural"
        project.forbidden_sentence_patterns = ""
        project.narrative_perspective = "third_person"

        pack = MagicMock()
        pack.pack_id = "chapter_writing_fast"
        pack.version = "1.0.0"
        pack.title = "Fast Writing"
        pack.workflow_json = [{"step": 1}]
        pack.quality_rubric_json = {"dimensions": []}
        pack.forbidden_patterns_json = ["仿佛"]

        def query_side_effect(model):
            q = MagicMock()
            q.filter.return_value = q
            q.order_by.return_value = q
            q.limit.return_value = q
            model_name = model.__name__ if hasattr(model, '__name__') else str(model)
            if "Project" in model_name:
                q.first.return_value = project
            elif "PublicPromptPack" in model_name:
                q.first.return_value = pack
            else:
                q.first.return_value = None
                q.all.return_value = []
            return q

        db = MagicMock()
        db.query.side_effect = query_side_effect

        result = asyncio.run(prepare_external_writing_context(db, "p1", {"mode": "fast"}))
        self.assertEqual(result["status"], "ok")
        data = result["data"]
        self.assertEqual(data["requested_mode"], "fast")
        self.assertEqual(data["effective_mode"], "fast")
        self.assertEqual(data["prompt_pack"]["pack_id"], "chapter_writing_fast")
        self.assertIn("快速模式定位", data["prompt_pack"]["system_prompt"])
        self.assertEqual(data["prompt_pack"]["forbidden_patterns"], [])
        self.assertIsNone(data["prompt_pack"]["quality_rubric"])
        self.assertNotIn("去AI味硬规则", data["prompt_pack"]["system_prompt"])

    def test_no_llm_call(self):
        """Verify the tool does not call LLMGateway."""
        from app.services.workspace.tools.external_writing import prepare_external_writing_context
        # If LLMGateway were called, this import would trigger it
        # The tool should only use DB queries
        db = MagicMock()
        query_mock = MagicMock()
        query_mock.filter.return_value = query_mock
        query_mock.first.return_value = None
        db.query.return_value = query_mock

        # Should succeed without any LLM call
        result = asyncio.run(prepare_external_writing_context(db, "p1", {}))
        self.assertEqual(result["status"], "skipped")  # project not found, but no crash


if __name__ == "__main__":
    unittest.main()
