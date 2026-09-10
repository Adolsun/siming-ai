"""Keep complete same-turn pages and protocol state inside the actual budget."""
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.services.conversation_context import (
    CapacityAssurance,
    ConversationContextError,
    ConversationContextErrorCode,
    ConversationIdentity,
    ConversationKind,
    ConversationMessage,
    GenerationModelBinding,
    NativeToolCall,
    NativeToolResult,
    ToolTransaction,
    Utf8ByteTokenCounter,
)
from app.services.conversation_context.assembly import assemble_context_step
from app.services.conversation_context.canonical import canonical_sha256, text_sha256
from app.services.conversation_context.contracts import ConversationRole
from app.services.conversation_context.protocol_validator import ModelToolCapability
from app.services.workspace.assistant_native_turn import WorkspaceNativeTurn


def test_consumed_long_chapter_pages_remain_exact_and_do_not_borrow_output_or_safety_space():
    body = '汉字汉文𠮷🙂\n' * 4000  # 20,000 Han characters plus emoji and newlines.
    page_chars = 5600  # Five pages, each below the actual 6,000-character read ceiling.
    transactions = []
    for index in range(5):
        transaction = ToolTransaction(
            transaction_id=f'transaction-{index}', assistant_message_id=f'assistant-{index}',
            assistant_content='', assistant_reasoning_content=f'visible reasoning {index}',
            assistant_provider_state=({'type': 'reasoning', 'id': f'opaque-{index}'},),
            calls=(NativeToolCall(f'call-{index}', 'search_chapters', json.dumps({
                'chapter_id': 'exact-chapter', 'content_offset_chars': index * page_chars,
                'content_chars': page_chars,
            })),),
        ).add_result(NativeToolResult(
            f'call-{index}', json.dumps({'status': 'ok', 'data': {
                'id': 'exact-chapter',
                'content': body[index * page_chars:(index + 1) * page_chars],
                'manifest_id': 'established-manifest',
            }}, ensure_ascii=False), result_ref=f'assistant_run_step:step-{index}',
            persisted_step_id=f'step-{index}',
        )).mark_delivered()
        transactions.append(transaction)
        # Exercise the actual workspace acknowledgement, not a test-only policy.
        WorkspaceNativeTurn._mark_delivered_transactions_consumed(SimpleNamespace(
            state=SimpleNamespace(tool_transactions=transactions),
        ))
        assert len(transactions) == index + 1
        assert all(item.state.value == 'consumed' for item in transactions)

    binding = GenerationModelBinding(
        task_type='assistant', provider='openai', model_name='test', normalized_model='openai:test',
        protocol='native', context_window_tokens=200_000, max_output_tokens=4096,
        token_counter_id='conservative.utf8_bytes.v1', capacity_assurance=CapacityAssurance.CONSERVATIVE,
        prompt_contract_hash=text_sha256('system'), tool_schema_hash=canonical_sha256([]),
        config_fingerprint='test',
    )
    options = dict(
        conversation=ConversationIdentity(kind=ConversationKind.WORKSPACE, id='conversation',
                                        revision=1, project_id='project'),
        turns=(), current_user_message=ConversationMessage(message_id='current', sequence_no=1,
                    role=ConversationRole.USER, content='继续当前任务'),
        model_binding=binding, token_counter=Utf8ByteTokenCounter(), system_prompt='system',
        current_tools=(), safety_margin_tokens=512, delivered_transactions=tuple(transactions),
        model_capability=ModelToolCapability(supports_native_tool_calling=True),
    )
    prepared = assemble_context_step(**options)
    messages = prepared.provider_messages
    results = [json.loads(m['content']) for m in messages if m['role'] == 'tool']
    assert ''.join(r['data']['content'] for r in results) == body
    assert all(r['data']['manifest_id'] == 'established-manifest' for r in results)
    assert [m for m in messages if m['role'] == 'assistant'] == [
        transaction.native_messages()[0] for transaction in transactions
    ]
    assert not any('[SERVER_VERIFIED_EXECUTION_RECEIPTS]' in m.get('content', '') for m in messages)
    assert prepared.budget.output_reserve_tokens == 4096
    assert prepared.budget.safety_margin_tokens == 512

    snapshot = [item.to_dict() for item in transactions]
    too_small = replace(binding, context_window_tokens=prepared.budget.current_input_tokens + 4096 + 512 - 1)
    with pytest.raises(ConversationContextError) as caught:
        assemble_context_step(**{**options, 'model_binding': too_small})
    assert caught.value.code is ConversationContextErrorCode.REQUIRED_STATE_OVER_CAPACITY
    assert [item.to_dict() for item in transactions] == snapshot
