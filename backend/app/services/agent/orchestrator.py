"""Plan orchestrator — executes a PlanGraph against the database with recovery support."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, AsyncGenerator

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.architecture.uow import commit_session

from ...database.models import (
    AgentPlan,
    AgentPlanStep,
    AgentRun,
    AssistantRun,
    ChapterWriteClaim,
    OperationRun,
)
from ..operation_runtime import current_operation_id, invoke_operation_action
from ..workspace.executor import execute_workspace_action
from ..workspace.idempotency import (
    acquire_chapter_write_claim,
    chapter_write_target_key,
    check_idempotency,
    fail_chapter_write_claim,
    generate_idempotency_key,
    validate_chapter_write_claim,
)
from ..workspace.registry import registry
from .plan_graph import PlanGraph, StepDef
from .step_args import resolve_step_args

_EXECUTABLE_STATUSES = {"pending", "blocked", "error"}
_SKIP_STATUSES = {"ok", "skipped"}

# Cataloging tools — handled by the cataloging service, not the workspace registry.
_CATALOGING_TOOLS = {"extract_facts", "resolve_targets", "apply_candidates"}
_FORMAL_CHAPTER_WRITE_TOOLS = {"create_chapter", "update_chapter"}
_LOCAL_CLI_WRITING_TOOLS = {"start_local_cli_agent_run", "wait_local_cli_agent_run"}


def _safe_json(data: Any, *, max_chars: int = 80_000) -> str:
    try:
        text = json.dumps(data, ensure_ascii=False, default=str)
    except Exception:
        text = json.dumps(str(data), ensure_ascii=False)
    if len(text) > max_chars:
        return text[:max_chars] + "...[truncated]"
    return text


def _extract_output_refs(result: dict) -> dict:
    """Extract stable reference IDs from a tool result."""
    refs: dict[str, str] = {}
    data = result.get("data") or {}
    if not isinstance(data, dict):
        return refs

    for key in ("draft_id", "content_ref", "chapter_id", "character_id",
                "worldbuilding_id", "outline_node_id", "relationship_id"):
        val = data.get(key)
        if val:
            refs[key] = str(val)

    # create_chapter returns id as chapter_id sometimes
    if "id" in data and "chapter_id" not in refs:
        tool = result.get("tool", "")
        if tool == "create_chapter":
            refs["chapter_id"] = str(data["id"])

    return refs


def _inject_plan_runtime_args(tool: str, args: dict[str, Any], plan: AgentPlan) -> dict[str, Any]:
    """Pass runtime settings from the plan into tools that accept them."""
    updated = dict(args)
    tool_def = registry.get(tool)
    input_schema = tool_def.input_schema if tool_def else {}

    accepts_model = (
        "model" in input_schema
        or bool(tool_def and "internal_llm" in tool_def.permission_tags)
        or bool(tool_def and tool_def.tool_type == "generator")
    )
    if plan.model and accepts_model and not updated.get("model"):
        updated["model"] = plan.model

    if tool == "chapter_writer" and not updated.get("mode"):
        if plan.name == "quality_chapter":
            updated["mode"] = "quality"
        elif plan.name == "fast_chapter":
            updated["mode"] = "fast"

    return updated


def _serialize_step(step: AgentPlanStep) -> dict:
    """Serialize a step to a frontend-compatible format (similar to AssistantRunStep)."""
    payload: dict[str, Any] = {
        "id": step.id,
        "step_key": step.step_key,
        "tool": step.tool,
        "status": step.status,
        "detail": step.detail,
        "error": step.error,
        "attempt_no": step.attempt_no or 1,
        "retry_of_step_id": step.retry_of_step_id,
        "resolved_step_id": step.resolved_step_id,
        "started_at": step.started_at.isoformat() if step.started_at else None,
        "completed_at": step.completed_at.isoformat() if step.completed_at else None,
        "created_at": step.created_at.isoformat() if step.created_at else None,
    }
    if step.args_json:
        try:
            payload["request"] = json.loads(step.args_json)
        except Exception:
            payload["request"] = step.args_json
    if step.result_json:
        try:
            payload["result"] = json.loads(step.result_json)
        except Exception:
            payload["result"] = step.result_json
    if step.output_refs:
        try:
            payload["output_refs"] = json.loads(step.output_refs)
        except Exception:
            payload["output_refs"] = step.output_refs
    return payload


class PlanOrchestrator:
    def __init__(self, db: Session, project_id: str):
        self.db = db
        self.project_id = project_id

    def create_plan(
        self,
        graph: PlanGraph,
        *,
        conversation_id: str | None = None,
        assistant_run_id: str | None = None,
        assistant_message_id: str | None = None,
        model: str | None = None,
    ) -> AgentPlan:
        now = datetime.utcnow()
        plan = AgentPlan(
            project_id=self.project_id,
            conversation_id=conversation_id,
            assistant_run_id=assistant_run_id,
            assistant_message_id=assistant_message_id,
            name=graph.name,
            status="pending",
            graph_json=_safe_json({
                "name": graph.name,
                "steps": {
                    k: {
                        "tool": s.tool,
                        "args": s.args,
                        "depends_on": s.depends_on,
                        "retry_policy": s.retry_policy,
                        "idempotency_key": s.idempotency_key,
                        "label": s.label,
                    }
                    for k, s in graph.steps.items()
                },
            }),
            model=model,
            created_at=now,
            updated_at=now,
        )
        self.db.add(plan)
        self.db.flush()

        for key, step_def in graph.steps.items():
            step = AgentPlanStep(
                plan_id=plan.id,
                project_id=self.project_id,
                step_key=key,
                tool=step_def.tool,
                args_json=_safe_json(step_def.args),
                depends_on_json=json.dumps(step_def.depends_on, ensure_ascii=False),
                status="pending",
                retry_policy=step_def.retry_policy,
                idempotency_key=step_def.idempotency_key,
                attempt_no=1,
                created_at=now,
                updated_at=now,
            )
            self.db.add(step)

        commit_session(self.db)
        self.db.refresh(plan)
        return plan

    async def execute_plan(self, plan_id: str) -> AsyncGenerator[dict, None]:
        plan = self._get_plan(plan_id)
        if not self._claim_plan_execution(plan):
            yield {
                "type": "plan_already_running",
                "plan_id": plan.id,
                "status": "running",
                "detail": "该计划已在运行，未重复启动写章任务。",
            }
            return
        graph = self._reconstruct_graph(plan)
        order = graph.topological_order()

        for step in plan.steps:
            if step.status in {"running", "interrupted", "cancelled"}:
                step.status = "pending"
                step.error = None
                step.completed_at = None

        commit_session(self.db)
        try:
            yield {"type": "plan_start", "plan_id": plan.id, "name": plan.name, "status": "running"}

            completed_keys: set[str] = set()
            collected_outputs: dict[str, dict] = self._collect_existing_outputs(plan)

            for step_key in order:
                step_row = self._get_step(plan.id, step_key)
                if not step_row:
                    continue

                if step_row.status in _SKIP_STATUSES:
                    completed_keys.add(step_key)
                    yield {"type": "step_skip", "step_key": step_key, "tool": step_row.tool, "status": step_row.status}
                    continue

                deps = json.loads(step_row.depends_on_json) if step_row.depends_on_json else []
                deps_met = all(d in completed_keys for d in deps)
                if not deps_met:
                    if step_row.status != "blocked":
                        step_row.status = "blocked"
                        step_row.detail = f"等待依赖步骤: {', '.join(d for d in deps if d not in completed_keys)}"
                        step_row.updated_at = datetime.utcnow()
                    commit_session(self.db)
                    yield {"type": "step_blocked", "step_key": step_key, "tool": step_row.tool, "detail": step_row.detail}
                    continue

                async for event in self._execute_step(
                    plan,
                    step_row,
                    graph.steps[step_key],
                    collected_outputs,
                ):
                    yield event
                    if event.get("type") == "step_result" and event.get("status") == "ok":
                        completed_keys.add(step_key)
                        self._unblock_ready_steps(plan, completed_keys)

            all_steps = self.db.query(AgentPlanStep).filter(AgentPlanStep.plan_id == plan.id).all()
            has_error = any(s.status == "error" for s in all_steps)
            has_blocked = any(s.status == "blocked" for s in all_steps)
            has_cancelled = any(s.status == "cancelled" for s in all_steps)

            if has_cancelled:
                plan.status = "cancelled"
                plan.error = "写章任务已取消"
            elif has_error:
                plan.status = "error"
                plan.error = "部分步骤执行失败"
            elif has_blocked:
                plan.status = "error"
                plan.error = "部分步骤被阻塞"
            else:
                plan.status = "completed"

            if plan.status == "error":
                self._release_plan_chapter_write(plan, error=plan.error or "章节写作计划未完成")

            now = datetime.utcnow()
            plan.updated_at = now
            plan.completed_at = now
            commit_session(self.db)

            yield {"type": "plan_end", "plan_id": plan.id, "status": plan.status, "error": plan.error}
        except asyncio.CancelledError:
            await self._cancel_local_cli_children(plan)
            self.mark_plan_cancelled(plan.id)
            raise
        finally:
            if plan.status not in {"completed", "error", "cancelled"}:
                await self._cancel_local_cli_children(plan)
            self._finalize_unfinished_plan(plan, detail="计划执行流提前关闭，已释放章节写作占用")

    async def resume_plan(self, plan_id: str) -> AsyncGenerator[dict, None]:
        plan: AgentPlan | None = None
        owns_execution = False
        try:
            plan = self._get_plan(plan_id)
            owns_execution = self._claim_plan_execution(plan)
            if not owns_execution:
                yield {
                    "type": "plan_already_running",
                    "plan_id": plan.id,
                    "status": "running",
                    "detail": "该计划已在运行，未重复恢复写章任务。",
                }
                return
            async for event in self._resume_plan_impl(plan_id):
                yield event
        except asyncio.CancelledError:
            if plan is not None and owns_execution:
                await self._cancel_local_cli_children(plan)
                self.mark_plan_cancelled(plan_id)
            raise
        finally:
            if plan is not None and owns_execution:
                if plan.status not in {"completed", "error", "cancelled"}:
                    await self._cancel_local_cli_children(plan)
                self._finalize_unfinished_plan(
                    plan,
                    detail="计划恢复流提前关闭，已释放章节写作占用",
                )

    async def _resume_plan_impl(self, plan_id: str) -> AsyncGenerator[dict, None]:
        plan = self._get_plan(plan_id)
        graph = self._reconstruct_graph(plan)
        order = graph.topological_order()

        plan.error = None
        plan.updated_at = datetime.utcnow()
        commit_session(self.db)

        # A prior process or explicit cancellation can leave a durable step
        # non-terminal. Resuming owns those steps again from their checkpoint.
        recoverable_steps = (
            self.db.query(AgentPlanStep)
            .filter(
                AgentPlanStep.plan_id == plan.id,
                AgentPlanStep.status.in_(["blocked", "interrupted", "cancelled", "running"]),
            )
            .all()
        )
        for s in recoverable_steps:
            s.status = "pending"
            s.error = None
            s.completed_at = None
            s.updated_at = datetime.utcnow()
        commit_session(self.db)

        yield {"type": "plan_start", "plan_id": plan.id, "name": plan.name, "status": "running"}

        completed_keys: set[str] = set()
        collected_outputs: dict[str, dict] = self._collect_existing_outputs(plan)

        for step_key in order:
            step_row = self._get_step(plan.id, step_key)
            if not step_row:
                continue

            if step_row.status in _SKIP_STATUSES:
                completed_keys.add(step_key)
                yield {"type": "step_skip", "step_key": step_key, "tool": step_row.tool, "status": step_row.status}
                continue

            deps = json.loads(step_row.depends_on_json) if step_row.depends_on_json else []
            deps_met = all(d in completed_keys for d in deps)
            if not deps_met:
                step_row.status = "blocked"
                step_row.detail = f"等待依赖步骤: {', '.join(d for d in deps if d not in completed_keys)}"
                step_row.updated_at = datetime.utcnow()
                commit_session(self.db)
                yield {"type": "step_blocked", "step_key": step_key, "tool": step_row.tool, "detail": step_row.detail}
                continue

            async for event in self._execute_step(plan, step_row, graph.steps[step_key], collected_outputs):
                yield event
                if event.get("type") == "step_result" and event.get("status") == "ok":
                    completed_keys.add(step_key)
                    self._unblock_ready_steps(plan, completed_keys)

        all_steps = self.db.query(AgentPlanStep).filter(AgentPlanStep.plan_id == plan.id).all()
        has_error = any(s.status == "error" for s in all_steps)
        has_blocked = any(s.status == "blocked" for s in all_steps)
        has_cancelled = any(s.status == "cancelled" for s in all_steps)

        if has_cancelled:
            plan.status = "cancelled"
            plan.error = "写章任务已取消"
        elif has_error:
            plan.status = "error"
            plan.error = "部分步骤执行失败"
        elif has_blocked:
            plan.status = "error"
            plan.error = "部分步骤被阻塞"
        else:
            plan.status = "completed"

        if plan.status == "error":
            self._release_plan_chapter_write(plan, error=plan.error or "章节写作计划未完成")

        now = datetime.utcnow()
        plan.updated_at = now
        plan.completed_at = now
        commit_session(self.db)

        yield {"type": "plan_end", "plan_id": plan.id, "status": plan.status, "error": plan.error}

    # ------------------------------------------------------------------
    # Resume from a specific step
    # ------------------------------------------------------------------

    async def resume_from_step(self, plan_id: str, step_key: str) -> AsyncGenerator[dict, None]:
        plan: AgentPlan | None = None
        owns_execution = False
        try:
            plan = self._get_plan(plan_id)
            owns_execution = self._claim_plan_execution(plan)
            if not owns_execution:
                yield {
                    "type": "plan_already_running",
                    "plan_id": plan.id,
                    "status": "running",
                    "detail": "该计划已在运行，未重复恢复写章任务。",
                }
                return
            async for event in self._resume_from_step_impl(plan_id, step_key):
                yield event
        except asyncio.CancelledError:
            if plan is not None and owns_execution:
                await self._cancel_local_cli_children(plan)
                self.mark_plan_cancelled(plan_id)
            raise
        finally:
            if plan is not None and owns_execution:
                if plan.status not in {"completed", "error", "cancelled"}:
                    await self._cancel_local_cli_children(plan)
                self._finalize_unfinished_plan(
                    plan,
                    detail="计划分步恢复流提前关闭，已释放章节写作占用",
                )

    async def _resume_from_step_impl(
        self,
        plan_id: str,
        step_key: str,
    ) -> AsyncGenerator[dict, None]:
        plan = self._get_plan(plan_id)
        graph = self._reconstruct_graph(plan)
        order = graph.topological_order()

        if step_key not in graph.steps:
            yield {"type": "error", "detail": f"步骤 {step_key} 不存在"}
            return

        # Find downstream keys + the target itself
        downstream = graph.downstream_keys(step_key)
        scope = {step_key, *downstream}

        plan.status = "running"
        plan.error = None
        plan.updated_at = datetime.utcnow()
        commit_session(self.db)

        # Reset scope steps
        scope_steps = (
            self.db.query(AgentPlanStep)
            .filter(
                AgentPlanStep.plan_id == plan.id,
                AgentPlanStep.step_key.in_(scope),
            )
            .all()
        )
        for s in scope_steps:
            if s.status in {"error", "blocked", "ok", "interrupted", "cancelled", "running"}:
                s.status = "pending"
                s.error = None
                s.completed_at = None
                s.updated_at = datetime.utcnow()
        commit_session(self.db)

        yield {"type": "plan_start", "plan_id": plan.id, "name": plan.name, "status": "running"}

        completed_keys: set[str] = set()
        collected_outputs: dict[str, dict] = self._collect_existing_outputs(plan)

        for step_key_item in order:
            if step_key_item not in scope:
                # Steps outside scope: treat their ok status as completed
                sr = self._get_step(plan.id, step_key_item)
                if sr and sr.status == "ok":
                    completed_keys.add(step_key_item)
                continue

            step_row = self._get_step(plan.id, step_key_item)
            if not step_row:
                continue

            if step_row.status in _SKIP_STATUSES:
                completed_keys.add(step_key_item)
                yield {"type": "step_skip", "step_key": step_key_item, "tool": step_row.tool, "status": step_row.status}
                continue

            deps = json.loads(step_row.depends_on_json) if step_row.depends_on_json else []
            deps_met = all(d in completed_keys for d in deps)
            if not deps_met:
                step_row.status = "blocked"
                step_row.detail = f"等待依赖步骤: {', '.join(d for d in deps if d not in completed_keys)}"
                step_row.updated_at = datetime.utcnow()
                commit_session(self.db)
                yield {"type": "step_blocked", "step_key": step_key_item, "tool": step_row.tool, "detail": step_row.detail}
                continue

            async for event in self._execute_step(plan, step_row, graph.steps[step_key_item], collected_outputs):
                yield event
                if event.get("type") == "step_result" and event.get("status") == "ok":
                    completed_keys.add(step_key_item)
                    self._unblock_ready_steps(plan, completed_keys)

        all_steps = self.db.query(AgentPlanStep).filter(AgentPlanStep.plan_id == plan.id).all()
        has_error = any(s.status == "error" for s in all_steps)
        has_blocked = any(s.status == "blocked" for s in all_steps)
        has_cancelled = any(s.status == "cancelled" for s in all_steps)

        if has_cancelled:
            plan.status = "cancelled"
            plan.error = "写章任务已取消"
        elif has_error:
            plan.status = "error"
            plan.error = "部分步骤执行失败"
        elif has_blocked:
            plan.status = "error"
            plan.error = "部分步骤被阻塞"
        else:
            plan.status = "completed"

        if plan.status == "error":
            self._release_plan_chapter_write(plan, error=plan.error or "章节写作计划未完成")

        now = datetime.utcnow()
        plan.updated_at = now
        plan.completed_at = now
        commit_session(self.db)

        yield {"type": "plan_end", "plan_id": plan.id, "status": plan.status, "error": plan.error}

    # ------------------------------------------------------------------
    # Retry a single step
    # ------------------------------------------------------------------

    async def retry_step(self, plan_id: str, step_key: str) -> dict:
        plan = self._get_plan(plan_id)
        graph = self._reconstruct_graph(plan)

        step_row = self._get_step(plan.id, step_key)
        if not step_row:
            raise ValueError(f"步骤 {step_key} 不存在")
        if step_row.status not in {"error", "blocked", "interrupted"}:
            raise ValueError(f"只能重试失败、阻塞或已中断的步骤，当前状态: {step_row.status}")

        step_def = graph.steps.get(step_key)
        if not step_def:
            raise ValueError(f"步骤定义 {step_key} 不存在")

        collected_outputs = self._collect_existing_outputs(plan)

        # Reset step state
        step_row.status = "pending"
        step_row.error = None
        step_row.detail = None
        step_row.updated_at = datetime.utcnow()
        commit_session(self.db)

        # Execute
        events = []
        try:
            async for event in self._execute_step(plan, step_row, step_def, collected_outputs):
                events.append(event)
        except asyncio.CancelledError:
            await self._cancel_local_cli_children(plan)
            self.mark_plan_cancelled(plan.id)
            raise
        finally:
            if step_row.status not in {"ok", "error", "blocked"}:
                self._release_plan_chapter_write(
                    plan,
                    error="步骤重试提前关闭，已释放章节写作占用",
                )

        return _serialize_step(step_row)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def get_plan(self, plan_id: str) -> AgentPlan:
        """Return one project-owned plan for HTTP and other application callers."""
        return self._get_plan(plan_id)

    def _claim_plan_execution(self, plan: AgentPlan) -> bool:
        """Atomically ensure only one execute/resume invocation owns a plan."""
        now = datetime.utcnow()
        claimed = self.db.execute(
            update(AgentPlan)
            .where(
                AgentPlan.id == plan.id,
                AgentPlan.project_id == self.project_id,
                AgentPlan.status != "running",
            )
            .values(
                status="running",
                error=None,
                completed_at=None,
                updated_at=now,
            ),
            execution_options={"synchronize_session": False},
        )
        commit_session(self.db)
        self.db.refresh(plan)
        return claimed.rowcount == 1

    def mark_plan_cancelled(self, plan_id: str, detail: str = "用户取消了任务") -> None:
        """Project an interrupted coroutine into durable plan and step state."""
        plan = self._get_plan(plan_id)
        now = datetime.utcnow()
        plan.status = "cancelled"
        plan.error = detail
        plan.updated_at = now
        plan.completed_at = now
        for step in plan.steps:
            if step.status == "running":
                step.status = "cancelled"
                step.error = detail
                step.detail = step.detail or detail
                step.updated_at = now
                step.completed_at = now
        self._release_plan_chapter_write(
            plan,
            status="cancelled",
            error=detail,
        )
        commit_session(self.db)

    def _get_plan(self, plan_id: str) -> AgentPlan:
        plan = self.db.query(AgentPlan).filter(
            AgentPlan.id == plan_id,
            AgentPlan.project_id == self.project_id,
        ).first()
        if not plan:
            raise ValueError("计划不存在")
        return plan

    def _get_step(self, plan_id: str, step_key: str) -> AgentPlanStep | None:
        return self.db.query(AgentPlanStep).filter(
            AgentPlanStep.plan_id == plan_id,
            AgentPlanStep.step_key == step_key,
        ).first()

    def _reconstruct_graph(self, plan: AgentPlan) -> PlanGraph:
        """Reconstruct a PlanGraph from the persisted plan + steps."""
        graph_data = json.loads(plan.graph_json)
        steps: dict[str, StepDef] = {}
        for key, sdata in graph_data.get("steps", {}).items():
            steps[key] = StepDef(
                tool=sdata["tool"],
                args=sdata.get("args", {}),
                depends_on=sdata.get("depends_on", []),
                retry_policy=sdata.get("retry_policy", "none"),
                idempotency_key=sdata.get("idempotency_key"),
                label=sdata.get("label", ""),
            )
        return PlanGraph(name=graph_data.get("name", plan.name), steps=steps)

    def _collect_existing_outputs(self, plan: AgentPlan) -> dict[str, dict]:
        """Collect outputs from already-completed steps for arg resolution."""
        outputs: dict[str, dict] = {}
        completed_steps = (
            self.db.query(AgentPlanStep)
            .filter(AgentPlanStep.plan_id == plan.id, AgentPlanStep.status == "ok")
            .all()
        )
        for s in completed_steps:
            if s.result_json:
                try:
                    outputs[s.step_key] = json.loads(s.result_json)
                except Exception:
                    pass
        return outputs

    def _unblock_ready_steps(self, plan: AgentPlan, completed_keys: set[str]) -> None:
        """Re-queue blocked steps whose dependencies are now all met."""
        blocked = (
            self.db.query(AgentPlanStep)
            .filter(AgentPlanStep.plan_id == plan.id, AgentPlanStep.status == "blocked")
            .all()
        )
        for s in blocked:
            deps = json.loads(s.depends_on_json) if s.depends_on_json else []
            if all(d in completed_keys for d in deps):
                s.status = "pending"
                s.detail = None
                s.updated_at = datetime.utcnow()
        commit_session(self.db)

    async def _execute_step(
        self,
        plan: AgentPlan,
        step_row: AgentPlanStep,
        step_def: StepDef,
        collected_outputs: dict[str, dict],
    ) -> AsyncGenerator[dict, None]:
        """Execute a single step, yielding progress events."""
        now = datetime.utcnow()

        # State machine guard
        if step_row.status in _SKIP_STATUSES:
            yield {"type": "step_skip", "step_key": step_row.step_key, "tool": step_row.tool, "status": step_row.status}
            return

        # Handle cataloging tools via the cataloging service
        if step_row.tool in _CATALOGING_TOOLS:
            async for event in self._execute_cataloging_step(plan, step_row, now):
                yield event
            return

        # Resolve before changing durable state so a chapter target can be
        # fenced before the costly writer call begins.
        raw_args = json.loads(step_row.args_json) if step_row.args_json else {}
        resolved_args = resolve_step_args(raw_args, collected_outputs)
        resolved_args = _inject_plan_runtime_args(step_row.tool, resolved_args, plan)

        if self._step_requires_chapter_reservation(plan, step_row, resolved_args):
            reservation_event = self._project_chapter_reservation(
                plan,
                step_row,
                resolved_args,
                collected_outputs,
                now,
            )
            if reservation_event is not None:
                yield reservation_event
                return

        if self._step_requires_resumed_chapter_claim(plan, step_row):
            writer_step = next(
                (candidate for candidate in plan.steps if candidate.tool == "chapter_writer"),
                None,
            )
            writer_args = (
                json.loads(writer_step.args_json)
                if writer_step and writer_step.args_json
                else {}
            )
            writer_args = resolve_step_args(writer_args, collected_outputs)
            reservation_event = self._project_chapter_reservation(
                plan,
                step_row,
                writer_args,
                collected_outputs,
                now,
            )
            if reservation_event is not None:
                yield reservation_event
                return

        # Mark as running
        step_row.status = "running"
        step_row.started_at = now
        step_row.updated_at = now
        commit_session(self.db)

        yield {
            "type": "step_start",
            "step_key": step_row.step_key,
            "tool": step_row.tool,
            "attempt_no": step_row.attempt_no,
        }

        # Check idempotency
        idem_key = step_row.idempotency_key
        if not idem_key:
            idem_key = generate_idempotency_key(self.db, step_row.tool, self.project_id, resolved_args)
            if idem_key:
                step_row.idempotency_key = idem_key
                commit_session(self.db)

        if idem_key:
            existing = check_idempotency(self.db, self.project_id, idem_key)
            if existing:
                step_row.status = "ok"
                step_row.result_json = _safe_json(existing)
                step_row.output_refs = json.dumps(_extract_output_refs(existing), ensure_ascii=False)
                step_row.detail = "已存在，跳过重复执行（幂等）"
                step_row.completed_at = datetime.utcnow()
                step_row.updated_at = datetime.utcnow()
                commit_session(self.db)

                collected_outputs[step_row.step_key] = existing
                yield {
                    "type": "step_result",
                    "step_key": step_row.step_key,
                    "tool": step_row.tool,
                    "status": "ok",
                    "detail": step_row.detail,
                    "data": existing.get("data", {}),
                }
                return

        # Execute the tool
        action = {"tool": step_row.tool, "arguments": resolved_args}
        try:
            result = await execute_workspace_action(self.db, self.project_id, action)
        except asyncio.CancelledError:
            step_row.status = "cancelled"
            step_row.error = "用户取消了任务"
            step_row.detail = step_row.detail or step_row.error
            step_row.completed_at = datetime.utcnow()
            step_row.updated_at = datetime.utcnow()
            commit_session(self.db)
            raise
        except Exception as exc:
            result = {"tool": step_row.tool, "status": "error", "detail": str(exc)}

        result_status = str(result.get("status") or "ok")
        if result_status == "ok" and step_row.tool in _FORMAL_CHAPTER_WRITE_TOOLS:
            cancelled_detail = self._formal_write_fence_error(plan)
            if cancelled_detail:
                self.db.rollback()
                self.db.expire_all()
                result_status = "cancelled"
                result = {
                    "tool": step_row.tool,
                    "status": "cancelled",
                    "detail": cancelled_detail,
                    "data": {},
                }
        if result_status in {"needs_confirmation", "blocked_rebuild", "stale", "interrupted"}:
            result_status = "blocked"
            result["status"] = "blocked"
        if result_status == "skipped" and (
            step_row.tool in _FORMAL_CHAPTER_WRITE_TOOLS
            or (plan.name == "local_cli_writing" and step_row.tool in _LOCAL_CLI_WRITING_TOOLS)
        ):
            result_status = "error"
            result["status"] = "error"
            result["detail"] = str(result.get("detail") or "正式写章步骤未执行，本轮未创建或修改章节")
        result_detail = str(result.get("detail") or "")

        step_row.result_json = _safe_json(result)
        step_row.output_refs = json.dumps(_extract_output_refs(result), ensure_ascii=False)
        step_row.detail = result_detail
        step_row.completed_at = datetime.utcnow()
        step_row.updated_at = datetime.utcnow()

        if result_status in {"error", "blocked", "cancelled"}:
            step_row.status = result_status
            step_row.error = result_detail if result_status in {"error", "cancelled"} else None

            # Block downstream steps
            downstream = self._get_step_keys_after(plan.id, step_row.step_key)
            for ds_key in downstream:
                ds_step = self._get_step(plan.id, ds_key)
                if ds_step and ds_step.status == "pending":
                    ds_step.status = "blocked"
                    ds_step.detail = f"上游步骤 {step_row.step_key} 失败"
                    ds_step.updated_at = datetime.utcnow()
            commit_session(self.db)
            self._release_plan_chapter_write(
                plan,
                status="cancelled" if result_status == "cancelled" else "failed",
                error=result_detail or "章节写作计划未完成",
            )

            yield {
                "type": "step_result",
                "step_key": step_row.step_key,
                "tool": step_row.tool,
                "status": result_status,
                "detail": result_detail,
                "data": result.get("data", {}),
            }
        else:
            step_row.status = "ok"
            commit_session(self.db)

            # Store output for downstream arg resolution
            collected_outputs[step_row.step_key] = result

            yield {
                "type": "step_result",
                "step_key": step_row.step_key,
                "tool": step_row.tool,
                "status": "ok",
                "detail": result_detail,
                "data": result.get("data", {}),
            }

    async def _execute_cataloging_step(
        self,
        plan: AgentPlan,
        step_row: AgentPlanStep,
        started_at: datetime,
    ) -> AsyncGenerator[dict, None]:
        """Execute a cataloging step while keeping the generic executor compact."""
        step_row.status = "running"
        step_row.started_at = started_at
        step_row.updated_at = started_at
        commit_session(self.db)
        yield {
            "type": "step_start",
            "step_key": step_row.step_key,
            "tool": step_row.tool,
            "label": step_row.detail or step_row.tool,
        }
        try:
            from ..cataloging.orchestrator import create_cataloging_job, stream_cataloging_job

            chapter_ids = step_row.args_json and json.loads(step_row.args_json).get("chapter_ids")
            job = create_cataloging_job(
                self.db,
                self.project_id,
                execution_mode="auto",
                model=plan.model,
                chapter_ids=chapter_ids if isinstance(chapter_ids, list) else None,
            )
            async for _event_str in stream_cataloging_job(self.project_id, job.id):
                pass
            step_row.status = "ok"
            step_row.detail = f"建档完成，共 {job.total_chapters} 章"
            step_row.result_json = _safe_json({
                "tool": step_row.tool,
                "status": "ok",
                "detail": step_row.detail,
                "data": {"job_id": job.id, "total_chapters": job.total_chapters},
            })
        except Exception as exc:
            step_row.status = "error"
            step_row.error = str(exc)[:2000]
            step_row.detail = f"建档失败: {exc}"
        step_row.completed_at = datetime.utcnow()
        step_row.updated_at = datetime.utcnow()
        commit_session(self.db)
        yield {
            "type": "step_result",
            "step_key": step_row.step_key,
            "tool": step_row.tool,
            "status": step_row.status,
            "detail": step_row.detail or "",
            "error": step_row.error,
            "data": json.loads(step_row.result_json).get("data", {}) if step_row.result_json else {},
        }

    def _chapter_save_step(self, plan: AgentPlan) -> AgentPlanStep | None:
        return next(
            (
                step
                for step in plan.steps
                if step.step_key == "create_chapter"
                and step.tool in {"create_chapter", "update_chapter"}
            ),
            None,
        )

    def _local_cli_start_step(self, plan: AgentPlan) -> AgentPlanStep | None:
        if plan.name != "local_cli_writing":
            return None
        return next(
            (step for step in plan.steps if step.tool == "start_local_cli_agent_run"),
            None,
        )

    def _chapter_claim_step(self, plan: AgentPlan) -> AgentPlanStep | None:
        """Return the durable step that carries this plan's chapter claim."""
        return self._chapter_save_step(plan) or self._local_cli_start_step(plan)

    def _step_requires_chapter_reservation(
        self,
        plan: AgentPlan,
        step_row: AgentPlanStep,
        resolved_args: dict[str, Any],
    ) -> bool:
        if step_row.tool == "chapter_writer":
            return self._chapter_save_step(plan) is not None
        return bool(
            plan.name == "local_cli_writing"
            and step_row.tool == "start_local_cli_agent_run"
            and str(resolved_args.get("task_type") or "").strip().lower() == "writing"
        )

    def _step_requires_resumed_chapter_claim(
        self,
        plan: AgentPlan,
        step_row: AgentPlanStep,
    ) -> bool:
        """Re-fence a saved writer draft before resuming evaluation/persistence."""
        if step_row.tool not in {"evaluate_chapter", "create_chapter", "update_chapter"}:
            return False
        writer_step = next(
            (candidate for candidate in plan.steps if candidate.tool == "chapter_writer"),
            None,
        )
        if not writer_step or writer_step.status != "ok":
            return False
        claim_step = self._chapter_claim_step(plan)
        # Only bridge-generated managed chapter plans carry a canonical claim
        # step. Keep legacy/custom plans executable instead of inventing a
        # target after their writer has already completed.
        if not claim_step:
            return False
        if not claim_step.args_json:
            return True
        try:
            claim_args = json.loads(claim_step.args_json)
        except Exception:
            return True
        return not validate_chapter_write_claim(
            self.db,
            project_id=self.project_id,
            target_key=str(claim_args.get("_chapter_target_key") or ""),
            idempotency_key=str(claim_args.get("_chapter_idempotency_key") or ""),
            claim_id=str(claim_args.get("_chapter_claim_id") or "") or None,
            claim_token=str(claim_args.get("_chapter_claim_token") or "") or None,
        )

    def _formal_write_fence_error(self, plan: AgentPlan) -> str | None:
        """Re-check durable cancellation state after a save handler returns."""
        assistant_run = (
            self.db.query(AssistantRun)
            .filter(AssistantRun.id == plan.assistant_run_id)
            .first()
            if plan.assistant_run_id
            else None
        )
        operation_id = getattr(assistant_run, "operation_id", None) or current_operation_id()
        operation = (
            self.db.query(OperationRun).filter(OperationRun.id == operation_id).first()
            if operation_id
            else None
        )
        if operation and operation.status in {"cancelled", "interrupted"}:
            return "写章任务已取消或中断，保存结果未被标记为成功。"

        claim_step = self._chapter_claim_step(plan)
        if not claim_step or not claim_step.args_json:
            return None
        try:
            claim_args = json.loads(claim_step.args_json)
        except Exception:
            return "章节写作占用信息损坏，保存结果未被标记为成功。"
        claim_id = str(claim_args.get("_chapter_claim_id") or "").strip()
        claim_token = str(claim_args.get("_chapter_claim_token") or "").strip()
        if not claim_id or not claim_token:
            return "章节写作占用缺失，保存结果未被标记为成功。"
        claim = (
            self.db.query(ChapterWriteClaim)
            .filter(
                ChapterWriteClaim.id == claim_id,
                ChapterWriteClaim.project_id == self.project_id,
                ChapterWriteClaim.claim_token == claim_token,
            )
            .first()
        )
        if not claim or claim.status in {"failed", "cancelled"}:
            return "章节写作占用已取消或失效，保存结果未被标记为成功。"
        return None

    def _project_chapter_reservation(
        self,
        plan: AgentPlan,
        step_row: AgentPlanStep,
        resolved_args: dict[str, Any],
        collected_outputs: dict[str, dict],
        now: datetime,
    ) -> dict[str, Any] | None:
        reservation = self._reserve_plan_chapter_write(plan, resolved_args)
        state = str(reservation.get("state") or "")
        if state == "acquired":
            return None
        result = reservation.get("result") or {
            "tool": step_row.tool,
            "status": "blocked",
            "detail": "同一章节已有写作任务，未重复启动。",
            "data": {},
        }
        if state == "completed":
            save_step = self._chapter_save_step(plan)
            is_local_cli = step_row.tool == "start_local_cli_agent_run"
            step_row.status = "ok" if is_local_cli else "skipped"
            step_row.result_json = _safe_json(result)
            step_row.output_refs = json.dumps(_extract_output_refs(result), ensure_ascii=False)
            step_row.detail = str(result.get("detail") or "章节已经完成")
            step_row.completed_at = now
            step_row.updated_at = now
            if is_local_cli:
                collected_outputs[step_row.step_key] = result
                for downstream_key in self._get_step_keys_after(plan.id, step_row.step_key):
                    downstream = self._get_step(plan.id, downstream_key)
                    if downstream and downstream.status == "pending":
                        downstream.status = "skipped"
                        downstream.result_json = _safe_json(result)
                        downstream.output_refs = json.dumps(
                            _extract_output_refs(result), ensure_ascii=False
                        )
                        downstream.detail = "章节已存在，未重复启动本机 CLI"
                        downstream.completed_at = now
                        downstream.updated_at = now
            elif save_step:
                for candidate in plan.steps:
                    if candidate.step_key == "evaluate_chapter":
                        candidate.status = "skipped"
                        candidate.detail = "章节已存在，跳过重复评估"
                        candidate.completed_at = now
                        candidate.updated_at = now
                save_step.status = "ok"
                save_step.result_json = _safe_json(result)
                save_step.output_refs = json.dumps(_extract_output_refs(result), ensure_ascii=False)
                save_step.detail = str(result.get("detail") or "已打开现有章节")
                save_step.completed_at = now
                save_step.updated_at = now
                collected_outputs[save_step.step_key] = result
            commit_session(self.db)
            return {
                "type": "step_result",
                "step_key": step_row.step_key,
                "tool": step_row.tool,
                "status": "ok",
                "detail": step_row.detail,
                "data": result.get("data", {}),
            }

        result_status = "error" if state == "invalid" else "blocked"
        result["status"] = result_status
        step_row.status = result_status
        step_row.result_json = _safe_json(result)
        step_row.output_refs = json.dumps(_extract_output_refs(result), ensure_ascii=False)
        step_row.detail = str(result.get("detail") or "同一章节已有写作任务")
        step_row.error = step_row.detail if result_status == "error" else None
        step_row.completed_at = now
        step_row.updated_at = now
        for downstream_key in self._get_step_keys_after(plan.id, step_row.step_key):
            downstream = self._get_step(plan.id, downstream_key)
            if downstream and downstream.status == "pending":
                downstream.status = "blocked"
                downstream.detail = f"上游步骤 {step_row.step_key} 未执行"
                downstream.updated_at = now
        commit_session(self.db)
        return {
            "type": "step_result",
            "step_key": step_row.step_key,
            "tool": step_row.tool,
            "status": result_status,
            "detail": step_row.detail,
            "data": result.get("data", {}),
        }

    def _reserve_plan_chapter_write(
        self,
        plan: AgentPlan,
        writer_args: dict[str, Any],
    ) -> dict[str, Any]:
        """Fence one chapter target before the costly writer is called."""
        claim_step = self._chapter_claim_step(plan)
        outline_node_id = str(writer_args.get("outline_node_id") or "").strip()
        if not claim_step or not outline_node_id:
            return {
                "state": "invalid",
                "result": {
                    "tool": claim_step.tool if claim_step else "chapter_writer",
                    "status": "error",
                    "detail": "写章计划缺少当前作品中的章节大纲，本轮未生成正文。",
                    "data": {},
                },
            }

        from ..workspace.utils import find_outline_by_title_or_id

        outline = find_outline_by_title_or_id(
            self.db,
            self.project_id,
            outline_node_id,
            node_type="chapter",
        )
        if not outline:
            return {
                "state": "invalid",
                "result": {
                    "tool": claim_step.tool,
                    "status": "error",
                    "detail": "未找到当前作品中的章节大纲，本轮未生成正文。请重新选择章节大纲。",
                    "data": {},
                },
            }

        target_key = chapter_write_target_key(
            self.project_id,
            outline_node_id=outline.id,
        )
        claim_args = json.loads(claim_step.args_json) if claim_step.args_json else {}
        rewrite = claim_step.tool == "update_chapter" or bool(
            writer_args.get("rewrite") or claim_args.get("rewrite")
        )
        idempotency_key = (
            f"rewrite_chapter:{self.project_id}:{outline.id}:{plan.id}"
            if rewrite
            else f"create_chapter:{self.project_id}:{outline.id}"
        )
        reservation = acquire_chapter_write_claim(
            self.db,
            project_id=self.project_id,
            target_key=target_key or "",
            idempotency_key=idempotency_key,
        )
        if reservation.get("state") == "acquired":
            assistant_run = (
                self.db.query(AssistantRun)
                .filter(AssistantRun.id == plan.assistant_run_id)
                .first()
                if plan.assistant_run_id
                else None
            )
            claim_metadata = {
                "_chapter_target_key": target_key,
                "_chapter_idempotency_key": idempotency_key,
                "_chapter_claim_id": reservation.get("claim_id"),
                "_chapter_claim_token": reservation.get("claim_token"),
                "parent_plan_id": plan.id,
                "parent_operation_id": getattr(assistant_run, "operation_id", None),
            }
            claim_args.update(claim_metadata)
            if rewrite:
                claim_args["rewrite"] = True
                claim_args["rewrite_request_id"] = plan.id
            claim_step.args_json = _safe_json(claim_args)
            claim_step.idempotency_key = idempotency_key
            claim_step.updated_at = datetime.utcnow()
            if claim_step.tool == "start_local_cli_agent_run":
                writer_args.update(claim_metadata)
                writer_args["rewrite"] = rewrite
            commit_session(self.db)
        return reservation

    def _release_plan_chapter_write(
        self,
        plan: AgentPlan,
        *,
        status: str = "failed",
        error: str,
    ) -> None:
        claim_step = self._chapter_claim_step(plan)
        if not claim_step or not claim_step.args_json:
            return
        try:
            claim_args = json.loads(claim_step.args_json)
        except Exception:
            return
        fail_chapter_write_claim(
            self.db,
            str(claim_args.get("_chapter_claim_id") or "") or None,
            str(claim_args.get("_chapter_claim_token") or "") or None,
            status=status,
            error=error,
        )

    def _finalize_unfinished_plan(self, plan: AgentPlan, *, detail: str) -> None:
        """Release a running chapter claim on every non-completed exit path."""
        if plan.status == "completed":
            return
        now = datetime.utcnow()
        if plan.status in {"pending", "running"}:
            plan.status = "interrupted"
            plan.error = detail
            plan.updated_at = now
            plan.completed_at = now
            for step in plan.steps:
                if step.status == "running":
                    step.status = "interrupted"
                    step.error = detail
                    step.detail = step.detail or detail
                    step.updated_at = now
                    step.completed_at = now
        self._release_plan_chapter_write(
            plan,
            status="cancelled" if plan.status == "cancelled" else "failed",
            error=plan.error or detail,
        )
        commit_session(self.db)

    def _local_cli_child_run_ids(self, plan: AgentPlan) -> list[str]:
        run_ids: list[str] = []
        for step in plan.steps:
            if step.tool != "start_local_cli_agent_run" or not step.result_json:
                continue
            try:
                result = json.loads(step.result_json)
            except Exception:
                continue
            data = result.get("data") if isinstance(result, dict) else None
            run_id = str((data or {}).get("run_id") or "").strip() if isinstance(data, dict) else ""
            if run_id and run_id not in run_ids:
                run_ids.append(run_id)
        return run_ids

    async def _cancel_local_cli_children(self, plan: AgentPlan) -> None:
        """Cascade a parent plan cancellation to managed local CLI operations."""
        for run_id in self._local_cli_child_run_ids(plan):
            run = (
                self.db.query(AgentRun)
                .filter(AgentRun.id == run_id, AgentRun.project_id == self.project_id)
                .first()
            )
            if not run or run.status in {"completed", "failed", "cancelled"}:
                continue
            invoked = False
            if run.operation_id:
                try:
                    invoked = await invoke_operation_action(run.operation_id, "cancel")
                except Exception:
                    invoked = False
            if not invoked:
                from ..external_agent.run_service import cancel_run

                cancel_run(self.db, run.id)
            self.db.expire_all()

    def _get_step_keys_after(self, plan_id: str, step_key: str) -> list[str]:
        """Get step keys that depend (transitively) on the given step."""
        all_steps = (
            self.db.query(AgentPlanStep)
            .filter(AgentPlanStep.plan_id == plan_id)
            .all()
        )
        downstream: list[str] = []
        queue = [step_key]
        visited = {step_key}
        while queue:
            current = queue.pop(0)
            for s in all_steps:
                deps = json.loads(s.depends_on_json) if s.depends_on_json else []
                if current in deps and s.step_key not in visited:
                    visited.add(s.step_key)
                    downstream.append(s.step_key)
                    queue.append(s.step_key)

        return downstream
