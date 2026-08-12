"""Diagnostic-quality regressions for open-ended system chat."""
from __future__ import annotations

import asyncio
import logging

import pytest

from app.core.exceptions import NotFoundError
from app.services.system_chat_completion import complete_system_chat


class _Gateway:
    @staticmethod
    def model_identity(_model):
        return "opencode_cli", "opencode/free"


def test_expected_model_readiness_failure_does_not_emit_a_traceback(caplog):
    async def fail_with_user_action(**_kwargs):
        raise NotFoundError("请先在系统设置中测试并启用")

    caplog.set_level(logging.WARNING, logger="app.services.system_chat_completion")
    with pytest.raises(RuntimeError):
        asyncio.run(complete_system_chat(
            message="继续",
            context={},
            model="opencode_cli:opencode/free",
            gateway=_Gateway,
            generic_completion=fail_with_user_action,
            extra_body=None,
        ))

    records = [record for record in caplog.records if record.message.startswith("System chat failed")]
    assert len(records) == 1
    assert records[0].exc_info is None


def test_unexpected_system_chat_failure_keeps_diagnostic_traceback(caplog):
    async def fail_unexpectedly(**_kwargs):
        raise RuntimeError("unexpected parser defect")

    caplog.set_level(logging.WARNING, logger="app.services.system_chat_completion")
    with pytest.raises(RuntimeError):
        asyncio.run(complete_system_chat(
            message="继续",
            context={},
            model="opencode_cli:opencode/free",
            gateway=_Gateway,
            generic_completion=fail_unexpectedly,
            extra_body=None,
        ))

    records = [record for record in caplog.records if record.message.startswith("System chat failed")]
    assert len(records) == 1
    assert records[0].exc_info is not None
