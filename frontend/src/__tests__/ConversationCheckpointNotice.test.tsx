import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ConversationCheckpointNotice } from '../components/assistant/ConversationCheckpointNotice'

const handlers = () => ({
  onOpen: vi.fn(),
  onClose: vi.fn(),
  onRebuild: vi.fn(),
  onCancel: vi.fn(),
  onNewConversation: vi.fn(),
})

describe('ConversationCheckpointNotice', () => {
  it('distinguishes capacity rejection from checkpoint failure without denying prior work', () => {
    render(<ConversationCheckpointNotice state={{ status: 'failed', error_code: 'tool_result_over_capacity',
      error_detail: '工具结果及下一步预留超过当前模型容量。' }} modalOpen={false} {...handlers()} />)
    expect(screen.getByText('上下文容量不足')).toBeInTheDocument()
    expect(screen.getByText(/后续步骤已暂停.*已有处理记录仍然保留/)).toBeInTheDocument()
    expect(screen.queryByText(/当前任务尚未执行/)).not.toBeInTheDocument()
    expect(screen.queryByText('较早上下文整理失败')).not.toBeInTheDocument()
  })
  it('does not present successful preparation or pending confirmation as a failed tool', () => {
    render(
      <ConversationCheckpointNotice
        state={{ status: 'ready', active_checkpoint_id: 'checkpoint-ready' }}
        detail={{
          id: 'checkpoint-ready', status: 'ready',
          execution_ledger: [
            { tool: 'prepare_task_context', status: 'ready', detail: '已就绪' },
            { tool: 'outline_writer', status: 'needs_confirmation', detail: '等待确认' },
            { tool: 'search_outline', status: 'error', detail: '执行失败' },
          ],
        }}
        modalOpen
        {...handlers()}
      />,
    )

    expect(screen.getByText('ready')).toHaveClass('ant-tag-green')
    expect(screen.getByText('needs_confirmation')).toHaveClass('ant-tag-orange')
    expect(screen.getByText('error')).toHaveClass('ant-tag-red')
    expect(screen.getByText('已就绪')).toBeInTheDocument()
    expect(screen.getByText('等待确认')).toBeInTheDocument()
  })

  it('can hide cancellation when the caller has no independently safe cancel API', () => {
    const actions = handlers()
    render(
      <ConversationCheckpointNotice
        state={{ status: 'compressing', latest_checkpoint_id: 'checkpoint-1' }}
        modalOpen
        canCancel={false}
        {...actions}
      />,
    )

    expect(screen.getByText('正在整理较早上下文')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '取消整理' })).not.toBeInTheDocument()
    expect(actions.onCancel).not.toHaveBeenCalled()
  })

  it('keeps failed checkpoints recoverable through a new author message', () => {
    const actions = handlers()
    render(
      <ConversationCheckpointNotice
        state={{
          status: 'failed',
          latest_checkpoint_id: 'checkpoint-failed',
          error_detail: '结构校验失败',
          retryable: true,
        }}
        modalOpen={false}
        canCancel={false}
        {...actions}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /发送新消息重试/ }))
    expect(actions.onRebuild).toHaveBeenCalledOnce()
  })
})
