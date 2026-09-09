"""The same durable status must mean the same thing to authors and the Agent."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.architecture.tool_status import tool_status_detail
from app.services.conversation_context.execution_ledger import tool_receipts_from_run_steps
from app.services.workspace.assistant_public_projection import public_tool_log

FIXTURE = json.loads((Path(__file__).resolve().parents[2] / 'contracts/fixtures/tool-status-v1.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', FIXTURE['cases'], ids=lambda case: case['status'])
def test_status_is_consistent_in_shared_contract_public_log_and_model_receipt(case):
    tool = FIXTURE['tool']
    private = 'private provider diagnostic and credentials'
    step = SimpleNamespace(id='status-step', tool=tool, status=case['status'],
                           output_refs=None, detail=private, error=private)
    receipt = tool_receipts_from_run_steps([step])[0]
    public = public_tool_log({'tool': tool, 'status': case['status'], 'detail': private})
    assert tool_status_detail(tool, case['status']) == public['detail'] == receipt.summary == case['detail']
    assert receipt.status == public['status'] == case['status']
    assert not receipt.write_committed
    assert private not in repr(receipt) + repr(public)


def test_ready_is_not_proof_that_a_write_was_committed():
    step = SimpleNamespace(id='write-step', tool='update_project_info', status='ready', output_refs=None)
    assert not tool_receipts_from_run_steps([step], write_tools={'update_project_info'})[0].write_committed
