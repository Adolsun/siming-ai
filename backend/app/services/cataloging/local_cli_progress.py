"""Bound candidate-stage CLI work by committed progress, not process output."""
from __future__ import annotations

import time

from app.database.models import CatalogingCandidate, CatalogingChapterRun, CatalogingJob
from app.services.tool_category_state import read_tool_category_audits

STALL_PREFIX = "cataloging_no_progress:"
CHECKPOINT_TERMINAL = "cataloging_checkpoint_committed"


class CandidateProgressProbe:
    """One instance spans all category switches in a candidate-stage turn."""

    def __init__(self, *, category_file, chapter_run_id, session_factory,
                 clock=time.monotonic, timeout_seconds=600, poll_seconds=1):
        self.category_file = category_file
        self.chapter_run_id = chapter_run_id
        self.session_factory = session_factory
        self.clock = clock
        self.timeout_seconds = timeout_seconds
        self.poll_seconds = poll_seconds
        self.last_progress = clock()
        self.next_poll = 0.0
        self.audit_count = 0
        self.failures = 0
        self.last_error = "尚未保存新的候选或完成候选集"
        self.checkpoint = self._checkpoint()[1]

    def _checkpoint(self):
        with self.session_factory() as db:
            run = db.get(CatalogingChapterRun, self.chapter_run_id)
            job = db.get(CatalogingJob, run.job_id) if run else None
            terminal = (
                not run or not job
                or job.status in {"paused", "paused_on_failure", "cancelled", "failed", "completed"}
                or (run.status == "awaiting_confirmation" and job.execution_mode == "manual")
                or run.status in {"completed",
                                  "completed_with_warnings", "skipped_by_user"}
            )
            # Exclude heartbeat timestamps; compare actual persisted candidate content.
            rows = db.query(
                CatalogingCandidate.id, CatalogingCandidate.raw_payload,
                CatalogingCandidate.edited_payload, CatalogingCandidate.status,
                CatalogingCandidate.target_id,
            ).filter_by(chapter_run_id=self.chapter_run_id).order_by(CatalogingCandidate.id).all()
            return terminal, tuple(tuple(row) for row in rows)

    def __call__(self):
        now = self.clock()
        if now < self.next_poll:
            return None
        self.next_poll = now + self.poll_seconds
        terminal, checkpoint = self._checkpoint()
        if terminal:
            return CHECKPOINT_TERMINAL
        changed = checkpoint != self.checkpoint
        if changed:
            self.checkpoint = checkpoint
            self.last_progress = now
            self.failures = 0
        audits = read_tool_category_audits(self.category_file)
        for audit in audits[self.audit_count:]:
            if audit.get("tool") != "save_external_cataloging_candidates":
                continue
            result = audit.get("result") or {}
            data = result.get("data") or {}
            # The audit is appended after commit. It may arrive a poll later than
            # the DB snapshot, so do not require both to be observed together.
            # Only the DB checkpoint resets the elapsed-time budget above.
            if (result.get("status") == "ok" and not audit.get("replayed")
                    and isinstance(data.get("candidates_saved"), int)
                    and data["candidates_saved"] > 0):
                self.failures = 0
                continue
            self.failures += 1
            errors = data.get("validation_errors") or data.get("missing_required_items")
            self.last_error = (
                "；".join(str(item) for item in errors[:3])
                if isinstance(errors, list) and errors
                else str(result.get("detail") or "重复提交，没有保存进展")
            )[:1200]
        self.audit_count = len(audits)
        if self.failures >= 3:
            return STALL_PREFIX + "候选连续三次提交未产生有效进展。" + self._detail()
        if now - self.last_progress >= self.timeout_seconds:
            return STALL_PREFIX + f"候选阶段已连续 {self.timeout_seconds:g} 秒没有保存进展。" + self._detail()
        return None

    def _detail(self):
        return "已停止本轮 CLI，保留已保存事实和候选。最近问题：" + self.last_error
