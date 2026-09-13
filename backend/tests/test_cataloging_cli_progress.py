"""Offline reproduction of noisy CLI loops with rejected/duplicate submissions."""
import asyncio
import sys
from unittest.mock import patch

import pytest

from app.ai.local_cli_monitor import CLITurnTerminal, communicate_with_cli_quota_detection
from app.services.cataloging.local_cli_progress import (
    CandidateProgressProbe, CHECKPOINT_TERMINAL, STALL_PREFIX,
)


@pytest.fixture
def harness():
    state = {"now": 0, "checkpoint": (), "terminal": False, "audits": []}
    with (
        patch.object(CandidateProgressProbe, "_checkpoint",
                     lambda self: (state["terminal"], state["checkpoint"])),
        patch("app.services.cataloging.local_cli_progress.read_tool_category_audits",
              side_effect=lambda _: state["audits"]),
    ):
        probe = CandidateProgressProbe(category_file="test", chapter_run_id="run",
                                       session_factory=None, clock=lambda: state["now"],
                                       poll_seconds=0)
        yield state, probe


def submission(status="skipped", **data):
    return {"tool": "save_external_cataloging_candidates",
            "result": {"status": status, "data": data}}


def test_three_rejections_stop_with_actionable_reason(harness):
    state, probe = harness
    for _ in range(2):
        state["audits"].append(submission(validation_errors=["最多 3 条候选；chapter_link 必须聚合为一条"]))
        assert probe() is None
    state["audits"].append(submission(validation_errors=["最多 3 条候选；chapter_link 必须聚合为一条"]))
    reason = probe()
    assert reason.startswith(STALL_PREFIX)
    assert "最多 3 条" in reason
    assert "保留已保存计划和候选" in reason


def test_read_tools_and_category_switch_do_not_reset_failure_budget(harness):
    state, probe = harness
    for _ in range(3):
        state["audits"].extend([submission(duplicates_skipped=1),
                                 {"tool": "set_tool_categories", "status": "ok"},
                                 {"tool": "get_next_external_cataloging_chapter", "status": "ok"}])
    assert probe().startswith(STALL_PREFIX)


def test_committed_progress_resets_budget_and_timer(harness):
    state, probe = harness
    state["audits"] = [submission(), submission()]
    assert probe() is None
    state["now"] = 599
    state["checkpoint"] = (("candidate", "new payload"),)
    state["audits"].append(submission("ok", candidates_saved=1))
    assert probe() is None
    state["now"] = 610
    state["audits"].append(submission())
    assert probe() is None
    assert probe.failures == 1
    state["now"] = 1199
    assert "600 秒" in probe()


def test_reported_success_without_storage_change_does_not_reset_timer(harness):
    state, probe = harness
    state["audits"] = [submission("ok", candidates_saved=1)] * 3
    state["now"] = 600
    assert probe().startswith(STALL_PREFIX)


def test_late_success_audit_does_not_count_as_failed_submission(harness):
    state, probe = harness
    state["checkpoint"] = (("candidate", "saved"),)
    assert probe() is None
    state["audits"] = [submission("ok", candidates_saved=1)]
    assert probe() is None
    assert probe.failures == 0


def test_committed_completion_or_user_pause_outranks_late_failure(harness):
    state, probe = harness
    state["audits"] = [submission()] * 3
    state["now"] = 900
    state["terminal"] = True
    assert probe() == CHECKPOINT_TERMINAL


def test_noisy_process_is_terminated_by_business_progress_probe(harness):
    state, probe = harness

    async def run():
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-u", "-c",
            "import time\nwhile True:\n print('still generating', flush=True)\n time.sleep(.01)",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )

        async def reject():
            await asyncio.sleep(.15)
            state["audits"] = [submission(validation_errors=["chapter_link 必须聚合为一条"])] * 3

        task = asyncio.create_task(reject())
        try:
            with pytest.raises(CLITurnTerminal, match="chapter_link"):
                await asyncio.wait_for(communicate_with_cli_quota_detection(
                    process, timeout_seconds=None, terminal_probe=probe,
                    stop_on_permission_request=False,
                ), timeout=8)
            assert process.returncode is not None
        finally:
            await task
            if process.returncode is None:
                process.kill()
                await process.wait()

    asyncio.run(run())
