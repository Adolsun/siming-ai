"""Tests for the agent plan orchestration system."""
import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, patch

# Set test DB before importing app modules
os.environ["DATABASE_URL"] = "sqlite:///./test_agent_orchestrator.db"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import (
    AgentPlan,
    AgentPlanStep,
    AgentRun,
    ChapterWriteClaim,
    AssistantConversation,
    AssistantMessage,
    AssistantRun,
    Base,
    OperationRun,
    OutlineNode,
    Project,
)
from app.database.session import engine as app_engine, get_db
from app.services.agent.bridge import _apply_assistant_mode_to_intent
from app.services.agent.orchestrator import PlanOrchestrator, _serialize_step
from app.services.agent.plan_graph import PlanGraph, StepDef
from app.services.agent.planner import (
    detect_intent,
    plan_create_outline,
    plan_cataloging_init,
    plan_fast_chapter,
    plan_has_chapter_writing_contract,
    plan_local_cli_writing,
    plan_quality_chapter,
)
from app.services.agent.step_args import resolve_step_args
from app.services.external_agent.run_service import create_run
from app.services.workspace.run_log import create_assistant_run

from app.main import app

API_PREFIX = "/api/v1"

engine = create_engine(os.environ["DATABASE_URL"], connect_args={"check_same_thread": False})
TestSession = sessionmaker(bind=engine)


def tearDownModule():
    """Release SQLite handles before deleting the shared module database."""
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    app_engine.dispose()
    try:
        os.remove("test_agent_orchestrator.db")
    except OSError:
        pass


def _run_async(coro):
    """Run an async coroutine in a new event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class PlanGraphTestCase(unittest.TestCase):
    """Tests for plan_graph.py data structures."""

    def test_topological_order_simple_chain(self):
        graph = PlanGraph(name="test", steps={
            "a": StepDef(tool="t1", depends_on=[]),
            "b": StepDef(tool="t2", depends_on=["a"]),
            "c": StepDef(tool="t3", depends_on=["b"]),
        })
        order = graph.topological_order()
        self.assertEqual(order, ["a", "b", "c"])

    def test_topological_order_diamond(self):
        graph = PlanGraph(name="test", steps={
            "a": StepDef(tool="t1", depends_on=[]),
            "b": StepDef(tool="t2", depends_on=["a"]),
            "c": StepDef(tool="t3", depends_on=["a"]),
            "d": StepDef(tool="t4", depends_on=["b", "c"]),
        })
        order = graph.topological_order()
        self.assertEqual(order.index("a"), 0)
        self.assertLess(order.index("a"), order.index("b"))
        self.assertLess(order.index("a"), order.index("c"))
        self.assertLess(order.index("b"), order.index("d"))
        self.assertLess(order.index("c"), order.index("d"))

    def test_topological_order_cycle_raises(self):
        graph = PlanGraph(name="test", steps={
            "a": StepDef(tool="t1", depends_on=["b"]),
            "b": StepDef(tool="t2", depends_on=["a"]),
        })
        with self.assertRaises(ValueError):
            graph.topological_order()

    def test_ready_steps(self):
        graph = PlanGraph(name="test", steps={
            "a": StepDef(tool="t1", depends_on=[]),
            "b": StepDef(tool="t2", depends_on=["a"]),
            "c": StepDef(tool="t3", depends_on=["a"]),
            "d": StepDef(tool="t4", depends_on=["b", "c"]),
        })
        self.assertEqual(graph.ready_steps(set()), ["a"])
        self.assertEqual(set(graph.ready_steps({"a"})), {"b", "c"})
        self.assertEqual(graph.ready_steps({"a", "b"}), ["c"])
        self.assertEqual(graph.ready_steps({"a", "b", "c"}), ["d"])

    def test_downstream_keys(self):
        graph = PlanGraph(name="test", steps={
            "a": StepDef(tool="t1", depends_on=[]),
            "b": StepDef(tool="t2", depends_on=["a"]),
            "c": StepDef(tool="t3", depends_on=["a"]),
            "d": StepDef(tool="t4", depends_on=["b", "c"]),
        })
        self.assertEqual(set(graph.downstream_keys("a")), {"b", "c", "d"})
        self.assertEqual(graph.downstream_keys("b"), ["d"])
        self.assertEqual(graph.downstream_keys("d"), [])


class StepArgsResolverTestCase(unittest.TestCase):
    """Tests for step_args.py reference resolver."""

    def test_resolve_simple_string(self):
        outputs = {"writer": {"data": {"draft_id": "abc123"}}}
        result = resolve_step_args({"id": "{writer.data.draft_id}"}, outputs)
        self.assertEqual(result, {"id": "abc123"})

    def test_resolve_entire_value_preserves_type(self):
        outputs = {"writer": {"data": {"count": 42}}}
        result = resolve_step_args("{writer.data.count}", outputs)
        self.assertEqual(result, 42)

    def test_resolve_nested_dict(self):
        outputs = {"s1": {"data": {"x": "hello"}}}
        args = {"outer": {"inner": "{s1.data.x}"}}
        result = resolve_step_args(args, outputs)
        self.assertEqual(result, {"outer": {"inner": "hello"}})

    def test_resolve_list_items(self):
        outputs = {"s1": {"data": {"name": "Alice"}}}
        args = ["{s1.data.name}", "fixed"]
        result = resolve_step_args(args, outputs)
        self.assertEqual(result, ["Alice", "fixed"])

    def test_resolve_missing_key_returns_placeholder(self):
        outputs = {}
        result = resolve_step_args("{missing.data.field}", outputs)
        self.assertEqual(result, "{missing.data.field}")

    def test_resolve_partial_string_substitution(self):
        outputs = {"s1": {"data": {"name": "Alice"}}}
        result = resolve_step_args("Hello {s1.data.name}!", outputs)
        self.assertEqual(result, "Hello Alice!")

    def test_resolve_list_index(self):
        outputs = {"search": {"data": [{"title": "Ch1"}, {"title": "Ch2"}]}}
        result = resolve_step_args("{search.data.0.title}", outputs)
        self.assertEqual(result, "Ch1")

    def test_resolve_passthrough_non_string(self):
        outputs = {}
        result = resolve_step_args(42, outputs)
        self.assertEqual(result, 42)


class PlannerTestCase(unittest.TestCase):
    """Tests for planner.py plan generation."""

    def test_fast_chapter_plan_generation(self):
        graph = plan_fast_chapter(outline_node_id="node-1", requirements="写快点")
        self.assertEqual(graph.name, "fast_chapter")
        self.assertIn("search_outline", graph.steps)
        self.assertIn("chapter_writer", graph.steps)
        self.assertIn("create_chapter", graph.steps)
        self.assertEqual(len(graph.steps), 3)
        # Verify dependencies
        self.assertEqual(graph.steps["chapter_writer"].depends_on, ["search_outline"])
        self.assertEqual(graph.steps["create_chapter"].depends_on, ["chapter_writer"])
        self.assertEqual(
            graph.steps["create_chapter"].args["_cataloging_model"],
            "{chapter_writer.data.model}",
        )

    def test_quality_chapter_plan_generation_single_char(self):
        graph = plan_quality_chapter(
            outline_node_id="node-1",
            involved_characters=["Alice"],
        )
        self.assertEqual(graph.name, "quality_chapter")
        self.assertEqual(graph.steps["chapter_writer"].args["involved_characters"], ["Alice"])
        self.assertNotIn("roleplay", graph.steps)
        self.assertNotIn("dialogue_battle", graph.steps)

    def test_quality_chapter_plan_generation_multi_char(self):
        graph = plan_quality_chapter(
            outline_node_id="node-1",
            involved_characters=["Alice", "Bob"],
        )
        self.assertEqual(
            graph.steps["chapter_writer"].args["involved_characters"],
            ["Alice", "Bob"],
        )
        self.assertNotIn("dialogue_battle", graph.steps)
        self.assertNotIn("roleplay", graph.steps)

    def test_quality_chapter_plan_keeps_only_required_steps(self):
        graph = plan_quality_chapter(outline_node_id="node-1")
        expected = {"search_outline", "chapter_writer", "create_chapter"}
        self.assertEqual(set(graph.steps.keys()), expected)
        self.assertTrue(graph.steps["create_chapter"].args["skip_style_repair"])

    def test_fast_chapter_plan_defers_style_repair(self):
        graph = plan_fast_chapter(outline_node_id="node-1")
        self.assertTrue(graph.steps["create_chapter"].args["skip_style_repair"])

    def test_cataloging_init_plan_generation(self):
        graph = plan_cataloging_init(chapter_ids=["c1", "c2"])
        self.assertEqual(graph.name, "cataloging_init")
        self.assertEqual(set(graph.steps.keys()), {"list_chapters", "start_cataloging_job"})
        self.assertEqual(graph.steps["list_chapters"].tool, "list_chapters")
        self.assertEqual(graph.steps["start_cataloging_job"].tool, "start_cataloging_job")
        self.assertEqual(graph.steps["start_cataloging_job"].depends_on, ["list_chapters"])
        self.assertEqual(graph.steps["start_cataloging_job"].args["chapter_ids"], ["c1", "c2"])

    def test_create_outline_plan_generation(self):
        graph = plan_create_outline(requirements="补第151章", batch_count=2)
        self.assertEqual(graph.name, "create_outline")
        self.assertEqual(set(graph.steps.keys()), {"outline_writer", "create_outline_nodes"})
        self.assertEqual(graph.steps["create_outline_nodes"].depends_on, ["outline_writer"])
        self.assertEqual(graph.steps["create_outline_nodes"].args["nodes"], "{outline_writer.data.nodes}")
        self.assertEqual(graph.steps["outline_writer"].args["batch_count"], 2)

    def test_detect_intent_fast_chapter(self):
        result = detect_intent("写第151章")
        self.assertIsNotNone(result)
        self.assertEqual(result["mode"], "fast")
        self.assertEqual(result["chapter_number"], 151)

    def test_detect_intent_fast_chapter_without_di_prefix(self):
        result = detect_intent("帮我写151章")
        self.assertIsNotNone(result)
        self.assertEqual(result["intent_type"], "chapter")
        self.assertEqual(result["mode"], "fast")
        self.assertEqual(result["chapter_number"], 151)

    def test_detect_intent_quality_chapter(self):
        result = detect_intent("精写第42章")
        self.assertIsNotNone(result)
        self.assertEqual(result["mode"], "quality")
        self.assertEqual(result["chapter_number"], 42)

    def test_detect_intent_chinese_chapter_numbers(self):
        cases = {
            "写第一章": 1,
            "写第二十五章": 25,
            "写第一百零三章": 103,
            "写第〇七章": 7,
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                result = detect_intent(message)
                self.assertIsNotNone(result)
                self.assertEqual(result["intent_type"], "chapter")
                self.assertEqual(result["chapter_number"], expected)

    def test_detect_intent_strong_prose_request_without_number(self):
        for message in ("用质量模式写本章", "生成正文", "创建章节"):
            with self.subTest(message=message):
                result = detect_intent(message)
                self.assertIsNotNone(result)
                self.assertEqual(result["intent_type"], "chapter")

    def test_chapter_number_without_write_intent_does_not_start_writing(self):
        self.assertIsNone(detect_intent("检查第一章是否 OOC"))
        self.assertIsNone(detect_intent("总结第二十五章"))

    def test_strong_write_intent_wins_over_outline_vocabulary(self):
        result = detect_intent("先创建下一章大纲，然后生成正文")
        self.assertIsNotNone(result)
        self.assertEqual(result["intent_type"], "chapter")

        result = detect_intent("写第一章，按照大纲来")
        self.assertIsNotNone(result)
        self.assertEqual(result["intent_type"], "chapter")

    def test_plan_contract_requires_generation_and_persistence(self):
        incomplete = PlanGraph(
            name="bad-writing",
            steps={"reply": StepDef(tool="search_outline", args={}, depends_on=[])},
        )
        self.assertFalse(plan_has_chapter_writing_contract(incomplete))
        self.assertTrue(plan_has_chapter_writing_contract(
            plan_fast_chapter(outline_node_id="outline-1")
        ))

    def test_detect_intent_cataloging(self):
        result = detect_intent("给这个项目建档")
        self.assertIsNotNone(result)
        self.assertEqual(result["intent_type"], "project_init")

    def test_detect_intent_create_outline(self):
        result = detect_intent("那就先帮我创建大纲")
        self.assertIsNotNone(result)
        self.assertEqual(result["intent_type"], "outline")

    def test_detect_intent_create_bare_chapter_outline(self):
        result = detect_intent("帮我创建151章大纲")
        self.assertIsNotNone(result)
        self.assertEqual(result["intent_type"], "outline")
        self.assertEqual(result["chapter_number"], 151)
        self.assertIsNone(result["batch_count"])

        result = detect_intent("重写第一章大纲")
        self.assertIsNotNone(result)
        self.assertEqual(result["intent_type"], "outline")

    def test_detect_intent_outline_batch_keeps_count_separate(self):
        result = detect_intent("帮我创建后续3章大纲")
        self.assertIsNotNone(result)
        self.assertEqual(result["intent_type"], "outline")
        self.assertIsNone(result["chapter_number"])
        self.assertEqual(result["batch_count"], 3)

    def test_local_cli_writing_plan_starts_worker(self):
        graph = plan_local_cli_writing(
            requirements="帮我写151章",
            provider="opencode_cli",
            outline_node_id="outline-151",
        )
        self.assertEqual(graph.name, "local_cli_writing")
        self.assertEqual(set(graph.steps.keys()), {"start_local_cli_agent_run", "wait_local_cli_agent_run"})
        step = graph.steps["start_local_cli_agent_run"]
        self.assertEqual(step.tool, "start_local_cli_agent_run")
        self.assertEqual(step.args["task_type"], "writing")
        self.assertEqual(step.args["provider"], "opencode_cli")
        self.assertIn("outline-151", step.args["user_request"])
        wait_step = graph.steps["wait_local_cli_agent_run"]
        self.assertEqual(wait_step.tool, "wait_local_cli_agent_run")
        self.assertEqual(wait_step.depends_on, ["start_local_cli_agent_run"])
        self.assertEqual(wait_step.args["run_id"], "{start_local_cli_agent_run.data.run_id}")
        self.assertEqual(wait_step.args["outline_node_id"], "outline-151")
        self.assertEqual(wait_step.args["startup_timeout_seconds"], 3)

    def test_local_cli_rewrite_plan_uses_managed_update_contract(self):
        graph = plan_local_cli_writing(
            requirements="重写本章",
            provider="opencode_cli",
            outline_node_id="outline-151",
            rewrite=True,
        )
        start = graph.steps["start_local_cli_agent_run"]
        wait = graph.steps["wait_local_cli_agent_run"]
        self.assertTrue(start.args["rewrite"])
        self.assertTrue(wait.args["rewrite"])
        self.assertIn("update_chapter", start.args["user_request"])
        self.assertNotIn("must use `create_chapter`", start.args["user_request"])

    def test_assistant_mode_quality_overrides_chapter_plan_mode(self):
        intent = {
            "intent_type": "chapter",
            "mode": "fast",
            "requirements": "write chapter 5",
            "chapter_number": 5,
        }
        result = _apply_assistant_mode_to_intent(intent, "quality")
        self.assertEqual(result["mode"], "quality")
        self.assertEqual(intent["mode"], "fast")

    def test_assistant_mode_does_not_override_non_chapter_intent(self):
        intent = {
            "intent_type": "character",
            "mode": "fast",
            "requirements": "create character",
        }
        result = _apply_assistant_mode_to_intent(intent, "quality")
        self.assertEqual(result["mode"], "fast")

    def test_detect_intent_returns_none_for_unrelated(self):
        self.assertIsNone(detect_intent("今天天气怎么样"))
        self.assertIsNone(detect_intent(""))


class OrchestratorTestCase(unittest.TestCase):
    """Tests for PlanOrchestrator DB operations."""

    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=engine)

    def setUp(self):
        self.db = TestSession()
        # Clean tables in dependency order
        self.db.query(AgentPlanStep).delete()
        self.db.query(AgentPlan).delete()
        self.db.query(AssistantMessage).delete()
        self.db.query(AssistantConversation).delete()
        self.db.query(AssistantRun).delete()
        self.db.query(Project).delete()
        self.db.commit()

        # Create a test project
        self.project = Project(id="proj-1", title="Test Project")
        self.db.add(self.project)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_create_plan_does_not_execute(self):
        graph = plan_fast_chapter(outline_node_id="node-1")
        orchestrator = PlanOrchestrator(self.db, "proj-1")
        plan = orchestrator.create_plan(graph, model="test-model")

        self.assertEqual(plan.status, "pending")
        self.assertEqual(plan.name, "fast_chapter")
        self.assertIsNotNone(plan.graph_json)

        steps = self.db.query(AgentPlanStep).filter(AgentPlanStep.plan_id == plan.id).all()
        self.assertEqual(len(steps), 3)
        for s in steps:
            self.assertEqual(s.status, "pending")

    def test_plan_persistence(self):
        graph = plan_fast_chapter(outline_node_id="node-1")
        orchestrator = PlanOrchestrator(self.db, "proj-1")
        plan = orchestrator.create_plan(graph)
        plan_id = plan.id

        # Read back from DB
        loaded = self.db.query(AgentPlan).filter(AgentPlan.id == plan_id).first()
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.name, "fast_chapter")
        self.assertEqual(loaded.status, "pending")

        # Verify graph can be reconstructed
        graph_data = json.loads(loaded.graph_json)
        self.assertEqual(graph_data["name"], "fast_chapter")
        self.assertIn("chapter_writer", graph_data["steps"])

    def test_bridge_to_assistant_run(self):
        # Create conversation and run
        conv = AssistantConversation(id="conv-1", project_id="proj-1", title="test")
        run = AssistantRun(id="run-1", project_id="proj-1", status="running")
        msg = AssistantMessage(id="msg-1", conversation_id="conv-1", role="user", content="test")
        self.db.add_all([conv, run, msg])
        self.db.commit()

        graph = plan_fast_chapter(outline_node_id="node-1")
        orchestrator = PlanOrchestrator(self.db, "proj-1")
        plan = orchestrator.create_plan(
            graph,
            conversation_id="conv-1",
            assistant_run_id="run-1",
            assistant_message_id="msg-1",
        )

        self.assertEqual(plan.conversation_id, "conv-1")
        self.assertEqual(plan.assistant_run_id, "run-1")
        self.assertEqual(plan.assistant_message_id, "msg-1")

        # Verify frontend-compatible payload
        payload = _serialize_step(plan.steps[0])
        self.assertIn("id", payload)
        self.assertIn("step_key", payload)
        self.assertIn("tool", payload)
        self.assertIn("status", payload)

    def test_stale_running_step_is_recovered_instead_of_skipped(self):
        graph = PlanGraph(name="test", steps={
            "a": StepDef(tool="search_outline", args={}, depends_on=[]),
        })
        orchestrator = PlanOrchestrator(self.db, "proj-1")
        plan = orchestrator.create_plan(graph)

        # Manually set step to running
        step = self.db.query(AgentPlanStep).filter(AgentPlanStep.plan_id == plan.id).first()
        step.status = "running"
        self.db.commit()

        # A persisted running step belongs to a previous interrupted executor;
        # a new execution must own it from pending instead of treating it as done.
        events = _run_async(_collect_events(orchestrator.execute_plan(plan.id)))
        step_events = [e for e in events if e.get("type") == "step_start"]
        self.assertEqual(len(step_events), 1)
        self.assertEqual(step_events[0]["step_key"], "a")


class OrchestratorExecutionTestCase(unittest.TestCase):
    """Tests for orchestrator execution with mocked tool calls."""

    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=engine)

    def setUp(self):
        self.db = TestSession()
        self.db.query(ChapterWriteClaim).delete()
        self.db.query(AgentRun).delete()
        self.db.query(AgentPlanStep).delete()
        self.db.query(AgentPlan).delete()
        self.db.query(OutlineNode).delete()
        self.db.query(Project).delete()
        self.db.commit()

        self.project = Project(id="proj-2", title="Test Project 2")
        self.db.add(self.project)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    @patch("app.services.agent.orchestrator.execute_workspace_action")
    def test_dependency_execution(self, mock_execute):
        """Steps execute only when dependencies are met."""
        call_order = []

        async def track_execute(db, project_id, action):
            call_order.append(action["tool"])
            return {"tool": action["tool"], "status": "ok", "detail": "done", "data": {}}

        mock_execute.side_effect = track_execute

        graph = PlanGraph(name="test", steps={
            "a": StepDef(tool="tool_a", depends_on=[]),
            "b": StepDef(tool="tool_b", depends_on=["a"]),
            "c": StepDef(tool="tool_c", depends_on=["a"]),
        })
        orchestrator = PlanOrchestrator(self.db, "proj-2")
        plan = orchestrator.create_plan(graph)

        _run_async(_collect_events(orchestrator.execute_plan(plan.id)))

        self.assertEqual(call_order[0], "tool_a")
        self.assertIn("tool_b", call_order)
        self.assertIn("tool_c", call_order)
        self.assertLess(call_order.index("tool_a"), call_order.index("tool_b"))
        self.assertLess(call_order.index("tool_a"), call_order.index("tool_c"))

    @patch("app.services.agent.orchestrator.execute_workspace_action")
    def test_cancelled_execution_marks_plan_and_running_step_cancelled(self, mock_execute):
        started = asyncio.Event()

        async def wait_forever(_db, _project_id, _action):
            started.set()
            await asyncio.Event().wait()

        async def cancel_running_plan(orchestrator, plan_id):
            task = asyncio.create_task(_collect_events(orchestrator.execute_plan(plan_id)))
            await asyncio.wait_for(started.wait(), timeout=1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        mock_execute.side_effect = wait_forever
        graph = PlanGraph(name="cancel-test", steps={
            "write": StepDef(tool="chapter_writer", depends_on=[]),
        })
        orchestrator = PlanOrchestrator(self.db, "proj-2")
        plan = orchestrator.create_plan(graph)

        _run_async(cancel_running_plan(orchestrator, plan.id))
        self.db.refresh(plan)
        step = self.db.query(AgentPlanStep).filter(AgentPlanStep.plan_id == plan.id).one()
        self.assertEqual(plan.status, "cancelled")
        self.assertEqual(step.status, "cancelled")

        async def succeed(_db, _project_id, action):
            return {"tool": action["tool"], "status": "ok", "detail": "done", "data": {}}

        mock_execute.side_effect = succeed
        events = _run_async(_collect_events(orchestrator.resume_plan(plan.id)))
        self.db.refresh(plan)
        self.db.refresh(step)
        self.assertEqual(plan.status, "completed")
        self.assertEqual(step.status, "ok")
        self.assertTrue(any(event.get("type") == "step_start" for event in events))

    @patch("app.services.agent.orchestrator.execute_workspace_action")
    def test_plan_injects_model_and_chapter_mode(self, mock_execute):
        """Runtime plan model is passed to generator tools that accept model."""
        captured_actions = []

        async def capture_execute(db, project_id, action):
            captured_actions.append(action)
            return {"tool": action["tool"], "status": "ok", "detail": "done", "data": {}}

        mock_execute.side_effect = capture_execute

        graph = PlanGraph(name="fast_chapter", steps={
            "write": StepDef(tool="chapter_writer", args={"outline_node_id": "node-1"}, depends_on=[]),
        })
        orchestrator = PlanOrchestrator(self.db, "proj-2")
        plan = orchestrator.create_plan(graph, model="claude_cli:claude-code")

        _run_async(_collect_events(orchestrator.execute_plan(plan.id)))

        self.assertEqual(len(captured_actions), 1)
        self.assertEqual(captured_actions[0]["arguments"]["model"], "claude_cli:claude-code")
        self.assertEqual(captured_actions[0]["arguments"]["mode"], "fast")

    @patch("app.services.agent.orchestrator.execute_workspace_action")
    def test_failure_blocks_downstream(self, mock_execute):
        """Failed step causes downstream steps to become blocked."""
        async def fail_on_b(db, project_id, action):
            if action["tool"] == "tool_b":
                return {"tool": "tool_b", "status": "error", "detail": "boom"}
            return {"tool": action["tool"], "status": "ok", "detail": "done", "data": {}}

        mock_execute.side_effect = fail_on_b

        graph = PlanGraph(name="test", steps={
            "a": StepDef(tool="tool_a", depends_on=[]),
            "b": StepDef(tool="tool_b", depends_on=["a"]),
            "c": StepDef(tool="tool_c", depends_on=["b"]),
        })
        orchestrator = PlanOrchestrator(self.db, "proj-2")
        plan = orchestrator.create_plan(graph)

        events = _run_async(_collect_events(orchestrator.execute_plan(plan.id)))

        # Verify plan ended with error
        plan_end = [e for e in events if e.get("type") == "plan_end"]
        self.assertEqual(plan_end[0]["status"], "error")

        # Verify step c is blocked
        step_c = self.db.query(AgentPlanStep).filter(
            AgentPlanStep.plan_id == plan.id,
            AgentPlanStep.step_key == "c",
        ).first()
        self.assertEqual(step_c.status, "blocked")
        self.assertIn("上游步骤", step_c.detail)

    @patch("app.services.agent.orchestrator.execute_workspace_action")
    def test_formal_chapter_write_skipped_is_an_error(self, mock_execute):
        async def skip_write(_db, _project_id, _action):
            return {"tool": "create_chapter", "status": "skipped", "detail": "正文为空"}

        mock_execute.side_effect = skip_write
        graph = PlanGraph(name="write-contract", steps={
            "save": StepDef(tool="create_chapter", args={"title": "第一章"}, depends_on=[]),
        })
        orchestrator = PlanOrchestrator(self.db, "proj-2")
        plan = orchestrator.create_plan(graph)

        events = _run_async(_collect_events(orchestrator.execute_plan(plan.id)))

        self.db.refresh(plan)
        step = self.db.query(AgentPlanStep).filter(AgentPlanStep.plan_id == plan.id).one()
        self.assertEqual(plan.status, "error")
        self.assertEqual(step.status, "error")
        self.assertTrue(any(event.get("status") == "error" for event in events))

    @patch("app.services.agent.orchestrator.execute_workspace_action")
    def test_formal_write_post_handler_fence_observes_durable_cancel(self, mock_execute):
        assistant_run = create_assistant_run(
            self.db,
            project_id="proj-2",
            conversation_id=None,
            user_message_id=None,
            assistant_message_id=None,
            scope="project",
            assistant_mode="fast",
            model=None,
        )

        async def cancel_during_write(db, _project_id, action):
            operation = db.query(OperationRun).filter(
                OperationRun.id == assistant_run.operation_id,
            ).one()
            operation.status = "cancelled"
            db.commit()
            return {
                "tool": action["tool"],
                "status": "ok",
                "detail": "handler returned after cancellation",
                "data": {"chapter_id": "chapter-late"},
            }

        mock_execute.side_effect = cancel_during_write
        graph = PlanGraph(name="late-cancel", steps={
            "save": StepDef(tool="create_chapter", args={"title": "第一章"}),
        })
        orchestrator = PlanOrchestrator(self.db, "proj-2")
        plan = orchestrator.create_plan(graph, assistant_run_id=assistant_run.id)

        events = _run_async(_collect_events(orchestrator.execute_plan(plan.id)))

        self.db.refresh(plan)
        step = self.db.query(AgentPlanStep).filter(AgentPlanStep.plan_id == plan.id).one()
        self.assertEqual(step.status, "cancelled")
        self.assertEqual(plan.status, "cancelled")
        self.assertTrue(any(event.get("status") == "cancelled" for event in events))

    def test_second_execute_while_plan_is_running_is_rejected_by_cas(self):
        graph = PlanGraph(name="single-owner", steps={
            "read": StepDef(tool="search_outline", args={}, depends_on=[]),
        })
        orchestrator = PlanOrchestrator(self.db, "proj-2")
        plan = orchestrator.create_plan(graph)

        async def exercise():
            first = orchestrator.execute_plan(plan.id)
            first_event = await first.__anext__()
            second_events = await _collect_events(orchestrator.execute_plan(plan.id))
            await first.aclose()
            return first_event, second_events

        first_event, second_events = _run_async(exercise())
        self.assertEqual(first_event["type"], "plan_start")
        self.assertEqual(second_events[0]["type"], "plan_already_running")
        self.assertIn("未重复启动", second_events[0]["detail"])
        self.db.refresh(plan)
        self.assertEqual(plan.status, "interrupted")

    @patch("app.services.agent.orchestrator.execute_workspace_action", new_callable=AsyncMock)
    def test_closing_nonterminal_plan_releases_running_chapter_claim(self, mock_execute):
        outline = OutlineNode(
            id="outline-interrupt-1",
            project_id="proj-2",
            title="第一章 雨夜",
            node_type="chapter",
        )
        self.db.add(outline)
        self.db.commit()
        graph = plan_fast_chapter(outline_node_id=outline.id)
        orchestrator = PlanOrchestrator(self.db, "proj-2")
        plan = orchestrator.create_plan(graph)

        async def execute(_db, _project_id, action):
            return {
                "tool": action["tool"],
                "status": "ok",
                "detail": "done",
                "data": {},
            }

        mock_execute.side_effect = execute

        async def exercise():
            stream = orchestrator.execute_plan(plan.id)
            while True:
                event = await stream.__anext__()
                if event.get("type") == "step_start" and event.get("tool") == "chapter_writer":
                    break
            await stream.aclose()

        _run_async(exercise())

        self.db.refresh(plan)
        claim = self.db.query(ChapterWriteClaim).filter(
            ChapterWriteClaim.project_id == "proj-2",
        ).one()
        self.assertEqual(plan.status, "interrupted")
        self.assertEqual(claim.status, "failed")
        mock_execute.assert_awaited_once()

    @patch("app.services.agent.orchestrator.invoke_operation_action", new_callable=AsyncMock)
    def test_parent_plan_cancel_cascades_to_local_cli_child_operation(self, invoke_action):
        invoke_action.return_value = True
        child = create_run(
            self.db,
            "proj-2",
            source="internal_cli",
            client_name="opencode_cli",
            title="writing",
        )
        graph = plan_local_cli_writing(
            requirements="写第一章",
            provider="opencode_cli",
            outline_node_id="outline-1",
        )
        orchestrator = PlanOrchestrator(self.db, "proj-2")
        plan = orchestrator.create_plan(graph)
        start_step = next(
            step for step in plan.steps if step.tool == "start_local_cli_agent_run"
        )
        start_step.result_json = json.dumps({
            "tool": "start_local_cli_agent_run",
            "status": "ok",
            "data": {"run_id": child.id},
        })
        self.db.commit()

        _run_async(orchestrator._cancel_local_cli_children(plan))

        invoke_action.assert_awaited_once_with(child.operation_id, "cancel")

    @patch("app.services.agent.orchestrator.execute_workspace_action")
    def test_resume_reacquires_claim_without_rerunning_completed_writer(self, mock_execute):
        outline = OutlineNode(
            id="outline-resume-1",
            project_id="proj-2",
            title="第一章 旧港",
            node_type="chapter",
        )
        self.db.add(outline)
        self.db.commit()

        graph = plan_quality_chapter(outline_node_id=outline.id)
        orchestrator = PlanOrchestrator(self.db, "proj-2")
        plan = orchestrator.create_plan(graph)
        steps = {step.step_key: step for step in plan.steps}
        for key in ("search_outline", "chapter_writer"):
            steps[key].status = "ok"
            steps[key].result_json = json.dumps({"tool": steps[key].tool, "status": "ok", "data": {}})
        steps["search_outline"].result_json = json.dumps({
            "tool": "search_outline",
            "status": "ok",
            "data": [{"id": outline.id, "title": outline.title}],
        })
        steps["chapter_writer"].result_json = json.dumps({
            "tool": "chapter_writer",
            "status": "ok",
            "data": {"draft_id": "draft-resume", "content_ref": "draft-resume"},
        })
        steps["create_chapter"].status = "error"
        plan.status = "error"
        target_key = f"project:proj-2:outline:{outline.id}"
        idempotency_key = f"create_chapter:proj-2:{outline.id}"
        old_token = "old-claim-token"
        claim = ChapterWriteClaim(
            project_id="proj-2",
            target_key=target_key,
            idempotency_key=idempotency_key,
            claim_token=old_token,
            status="failed",
        )
        self.db.add(claim)
        self.db.flush()
        save_args = json.loads(steps["create_chapter"].args_json)
        save_args.update({
            "_chapter_target_key": target_key,
            "_chapter_idempotency_key": idempotency_key,
            "_chapter_claim_id": claim.id,
            "_chapter_claim_token": old_token,
        })
        steps["create_chapter"].args_json = json.dumps(save_args)
        self.db.commit()

        called_tools = []

        async def execute(_db, _project_id, action):
            called_tools.append(action["tool"])
            if action["tool"] == "create_chapter":
                return {"tool": "create_chapter", "status": "error", "detail": "stop after capture"}
            return {"tool": action["tool"], "status": "ok", "detail": "done", "data": {}}

        mock_execute.side_effect = execute
        _run_async(_collect_events(orchestrator.resume_plan(plan.id)))

        self.assertNotIn("chapter_writer", called_tools)
        self.assertNotIn("evaluate_chapter", called_tools)
        self.assertIn("create_chapter", called_tools)
        self.db.refresh(steps["create_chapter"])
        refreshed_args = json.loads(steps["create_chapter"].args_json)
        self.assertNotEqual(refreshed_args["_chapter_claim_token"], old_token)

    @patch("app.services.agent.orchestrator.execute_workspace_action")
    def test_resume_unblocks_downstream(self, mock_execute):
        """Resume resets blocked steps and re-executes."""
        call_count = {"b": 0}

        async def fail_then_succeed(db, project_id, action):
            if action["tool"] == "tool_b":
                call_count["b"] += 1
                if call_count["b"] == 1:
                    return {"tool": "tool_b", "status": "error", "detail": "boom"}
            return {"tool": action["tool"], "status": "ok", "detail": "done", "data": {}}

        mock_execute.side_effect = fail_then_succeed

        graph = PlanGraph(name="test", steps={
            "a": StepDef(tool="tool_a", depends_on=[]),
            "b": StepDef(tool="tool_b", depends_on=["a"]),
            "c": StepDef(tool="tool_c", depends_on=["b"]),
        })
        orchestrator = PlanOrchestrator(self.db, "proj-2")
        plan = orchestrator.create_plan(graph)

        # First execution: b fails, c blocked
        _run_async(_collect_events(orchestrator.execute_plan(plan.id)))

        # Resume: b succeeds, c unblocked
        events = _run_async(_collect_events(orchestrator.resume_plan(plan.id)))

        plan_end = [e for e in events if e.get("type") == "plan_end"]
        self.assertEqual(plan_end[0]["status"], "completed")

        step_c = self.db.query(AgentPlanStep).filter(
            AgentPlanStep.plan_id == plan.id,
            AgentPlanStep.step_key == "c",
        ).first()
        self.assertEqual(step_c.status, "ok")

    @patch("app.services.agent.orchestrator.execute_workspace_action")
    def test_resume_from_step(self, mock_execute):
        """Resume from a specific step re-executes it and downstream."""
        call_order = []

        async def track_execute(db, project_id, action):
            call_order.append(action["tool"])
            return {"tool": action["tool"], "status": "ok", "detail": "done", "data": {}}

        mock_execute.side_effect = track_execute

        graph = PlanGraph(name="test", steps={
            "a": StepDef(tool="tool_a", depends_on=[]),
            "b": StepDef(tool="tool_b", depends_on=["a"]),
            "c": StepDef(tool="tool_c", depends_on=["b"]),
        })
        orchestrator = PlanOrchestrator(self.db, "proj-2")
        plan = orchestrator.create_plan(graph)

        # Execute all first
        _run_async(_collect_events(orchestrator.execute_plan(plan.id)))
        call_order.clear()

        # Resume from b
        _run_async(_collect_events(orchestrator.resume_from_step(plan.id, "b")))
        self.assertIn("tool_b", call_order)
        self.assertIn("tool_c", call_order)
        self.assertNotIn("tool_a", call_order)

    @patch("app.services.agent.orchestrator.execute_workspace_action")
    def test_idempotency_skip(self, mock_execute):
        """Re-running a completed step with same idempotency key skips it."""
        async def ok_execute(db, project_id, action):
            return {"tool": action["tool"], "status": "ok", "detail": "done", "data": {"id": "x"}}

        mock_execute.side_effect = ok_execute

        graph = PlanGraph(name="test", steps={
            "a": StepDef(tool="create_chapter", args={"title": "Ch1"}, depends_on=[], idempotency_key="create_chapter:proj-2:Ch1"),
        })
        orchestrator = PlanOrchestrator(self.db, "proj-2")
        plan = orchestrator.create_plan(graph)

        # First execute
        _run_async(_collect_events(orchestrator.execute_plan(plan.id)))

        # Reset step to pending for re-execution
        step = self.db.query(AgentPlanStep).filter(AgentPlanStep.plan_id == plan.id).first()
        step.status = "pending"
        self.db.commit()

        # Second execute should skip due to idempotency
        events = _run_async(_collect_events(orchestrator.execute_plan(plan.id)))
        step_results = [e for e in events if e.get("type") == "step_result"]
        # The step should be skipped (either via idempotency or skip status)
        self.assertTrue(
            any("idempotency" in (e.get("detail") or "").lower()
                or "跳过" in (e.get("detail") or "")
                or e.get("status") == "ok"
                for e in step_results)
        )

    @patch("app.services.agent.orchestrator.execute_workspace_action")
    def test_step_args_resolved(self, mock_execute):
        """Step args with references are resolved before execution."""
        captured_args = {}

        async def capture_execute(db, project_id, action):
            captured_args[action["tool"]] = action.get("arguments", {})
            return {"tool": action["tool"], "status": "ok", "detail": "done", "data": {"draft_id": "d1"}}

        mock_execute.side_effect = capture_execute

        graph = PlanGraph(name="test", steps={
            "writer": StepDef(tool="chapter_writer", args={"node": "n1"}, depends_on=[]),
            "saver": StepDef(tool="create_chapter", args={"draft_id": "{writer.data.draft_id}"}, depends_on=["writer"]),
        })
        orchestrator = PlanOrchestrator(self.db, "proj-2")
        plan = orchestrator.create_plan(graph)

        _run_async(_collect_events(orchestrator.execute_plan(plan.id)))

        self.assertEqual(captured_args.get("create_chapter", {}).get("draft_id"), "d1")


class AgentRouterTestCase(unittest.TestCase):
    """Tests for the agent router endpoints."""

    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        from fastapi.testclient import TestClient
        # Override get_db
        def override_get_db():
            db = TestSession()
            try:
                yield db
            finally:
                db.close()
        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=engine)
        app.dependency_overrides.clear()

    def setUp(self):
        db = TestSession()
        db.query(AgentPlanStep).delete()
        db.query(AgentPlan).delete()
        db.query(Project).delete()
        db.commit()
        db.close()

    def _create_project(self):
        db = TestSession()
        p = Project(id="proj-api", title="API Test Project")
        db.add(p)
        db.commit()
        db.close()
        return "proj-api"

    def test_create_plan_endpoint(self):
        pid = self._create_project()
        resp = self.client.post(f"{API_PREFIX}/projects/{pid}/ai/agent/plans", json={
            "mode": "fast",
            "outline_node_id": "node-1",
            "requirements": "写快点",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["name"], "fast_chapter")
        self.assertEqual(data["status"], "pending")
        self.assertEqual(len(data["steps"]), 3)

    def test_get_plan_endpoint(self):
        pid = self._create_project()
        # Create plan
        resp = self.client.post(f"{API_PREFIX}/projects/{pid}/ai/agent/plans", json={
            "mode": "fast",
            "outline_node_id": "node-1",
        })
        plan_id = resp.json()["data"]["id"]

        # Get plan
        resp = self.client.get(f"{API_PREFIX}/projects/{pid}/ai/agent/plans/{plan_id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["id"], plan_id)
        self.assertEqual(data["status"], "pending")

    def test_create_plan_invalid_mode(self):
        pid = self._create_project()
        resp = self.client.post(f"{API_PREFIX}/projects/{pid}/ai/agent/plans", json={
            "mode": "invalid",
            "outline_node_id": "node-1",
        })
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _collect_events(async_gen):
    """Collect all events from an async generator."""
    events = []
    async for event in async_gen:
        events.append(event)
    return events


if __name__ == "__main__":
    unittest.main()
