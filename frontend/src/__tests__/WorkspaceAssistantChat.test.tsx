import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { mockDelete, mockGet, mockPost } = vi.hoisted(() => ({
  mockDelete: vi.fn(),
  mockGet: vi.fn(),
  mockPost: vi.fn(),
}))

vi.mock('../api/client', () => ({
  apiClient: { delete: mockDelete, get: mockGet, post: mockPost },
}))

import WorkspaceAssistantChat from '../components/WorkspaceAssistantChat'

const encoder = new TextEncoder()

function sse(payload: unknown) {
  return `data: ${typeof payload === 'string' ? payload : JSON.stringify(payload)}\n\n`
}

function createControlledResponse(initialChunks: string[] = []) {
  const chunks = initialChunks.map((chunk) => encoder.encode(chunk))
  let closed = false
  let failure: unknown = null
  let pending: {
    resolve: (value: ReadableStreamReadResult<Uint8Array>) => void
    reject: (reason?: unknown) => void
  } | null = null

  const settle = () => {
    if (!pending) return
    const next = pending
    pending = null
    if (failure) next.reject(failure)
    else if (chunks.length) next.resolve({ done: false, value: chunks.shift()! })
    else if (closed) next.resolve({ done: true, value: undefined })
    else pending = next
  }

  const reader = {
    read: vi.fn(() => {
      if (failure) return Promise.reject(failure)
      if (chunks.length) return Promise.resolve({ done: false, value: chunks.shift()! })
      if (closed) return Promise.resolve({ done: true, value: undefined })
      return new Promise<ReadableStreamReadResult<Uint8Array>>((resolve, reject) => {
        pending = { resolve, reject }
      })
    }),
  }

  return {
    response: { ok: true, status: 200, body: { getReader: () => reader } } as unknown as Response,
    bindSignal(signal?: AbortSignal | null) {
      signal?.addEventListener('abort', () => {
        failure = new DOMException('aborted', 'AbortError')
        settle()
      }, { once: true })
    },
    close() {
      closed = true
      settle()
    },
  }
}

const conversationEvent = sse({
  type: 'conversation',
  conversation: { id: 'conversation-1', project_id: 'project-1', title: '第一章' },
  user_message: {
    id: 'user-1', conversation_id: 'conversation-1', role: 'user', content: '写第一章', status: 'completed',
  },
  assistant_message: {
    id: 'assistant-1', conversation_id: 'conversation-1', role: 'assistant', content: '正在分析需求...', status: 'running', payload: null,
  },
})

const runEvent = sse({
  type: 'run',
  run: { id: 'run-1', operation_id: 'operation-1', status: 'running', phase: 'writing' },
})

const completedRunDetail = {
  code: 0,
  message: 'ok',
  data: {
    run: { id: 'run-1', operation_id: 'operation-1', status: 'completed', phase: 'completed' },
    assistant_message: {
      id: 'assistant-1',
      conversation_id: 'conversation-1',
      role: 'assistant',
      content: '正文已保存',
      status: 'completed',
      payload: { reply: '正文已保存', tool_logs: [], actions: [], applied_actions: [] },
    },
    steps: [],
  },
}

function renderChat(onApplied = vi.fn()) {
  const view = render(
    <WorkspaceAssistantChat
      projectId="project-1"
      scope="project"
      defaultModel="openai:test"
      modelOptions={[{ value: 'openai:test', label: 'OpenAI · test' }]}
      onApplied={onApplied}
    />,
  )
  return { ...view, onApplied }
}

async function sendChapterRequest() {
  const user = userEvent.setup()
  await user.type(screen.getByPlaceholderText(/告诉AI你想写什么/), '写第一章')
  await user.click(screen.getByRole('button', { name: /发送/ }))
  await screen.findByText('任务已创建：run-1')
  return user
}

describe('WorkspaceAssistantChat cancellation and recovery', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.unstubAllGlobals()
    mockGet.mockResolvedValue({ data: { data: { items: [], total: 0 } } })
    mockDelete.mockResolvedValue({ data: { data: null } })
    mockPost.mockResolvedValue({ data: { data: { status: 'cancelled' } } })
  })

  it('submits only one cancellation and exposes the pending state', async () => {
    const stream = createControlledResponse([conversationEvent + runEvent])
    vi.stubGlobal('fetch', vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      stream.bindSignal(init?.signal)
      return Promise.resolve(stream.response)
    }))
    let resolveCancel!: (value: unknown) => void
    mockPost.mockReturnValue(new Promise((resolve) => { resolveCancel = resolve }))
    renderChat()
    await sendChapterRequest()

    const cancelButton = screen.getByRole('button', { name: '取消当前任务' })
    fireEvent.click(cancelButton)
    fireEvent.click(cancelButton)

    expect(mockPost).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: '正在取消任务' })).toBeDisabled()
    await act(async () => {
      resolveCancel({ data: { data: { status: 'cancelled' } } })
    })
    expect(within(screen.getByTestId('project-ai-chat')).getByRole('status')).toHaveTextContent('已停止后续执行')
  })

  it('recovers the authoritative completed result after a detached stream ends', async () => {
    const stream = createControlledResponse([conversationEvent + runEvent])
    stream.close()
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/workspace-assistant/stream')) {
        stream.bindSignal(init?.signal)
        return Promise.resolve(stream.response)
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => completedRunDetail,
      } as Response)
    })
    vi.stubGlobal('fetch', fetchMock)
    const { onApplied } = renderChat()
    await sendChapterRequest()

    expect(await screen.findByText('正文已保存')).toBeInTheDocument()
    expect(screen.getByText(/已完成 #run-1/)).toBeInTheDocument()
    expect(onApplied).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/projects/project-1/ai/assistant/runs/run-1',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it('stops polling immediately on a fatal run lookup error', async () => {
    const stream = createControlledResponse([conversationEvent + runEvent])
    stream.close()
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes('/workspace-assistant/stream')) {
        stream.bindSignal(init?.signal)
        return Promise.resolve(stream.response)
      }
      return Promise.resolve({
        ok: false,
        status: 404,
        json: async () => ({ detail: '任务不存在' }),
      } as Response)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderChat()
    await sendChapterRequest()

    expect(await within(screen.getByTestId('project-ai-chat')).findByRole('status')).toHaveTextContent(
      '任务不存在。请在任务中心查看结果。',
    )
    await waitFor(() => expect(screen.getByRole('button', { name: /发送/ })).toBeInTheDocument())
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('reconciles a 409 cancellation response instead of showing a false failure', async () => {
    const stream = createControlledResponse([conversationEvent + runEvent])
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes('/workspace-assistant/stream')) {
        stream.bindSignal(init?.signal)
        return Promise.resolve(stream.response)
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => completedRunDetail } as Response)
    })
    vi.stubGlobal('fetch', fetchMock)
    const conflict = Object.assign(new Error('该任务当前不支持此操作'), { response: { status: 409 } })
    mockPost.mockRejectedValue(conflict)
    renderChat()
    const user = await sendChapterRequest()

    await user.click(screen.getByRole('button', { name: '取消当前任务' }))
    expect(await screen.findByText('正文已保存')).toBeInTheDocument()
    expect(within(screen.getByTestId('project-ai-chat')).getByRole('status')).toHaveTextContent('任务已结束')
    expect(mockPost).toHaveBeenCalledTimes(1)
  })

  it('aborts only the browser subscription when unmounted', async () => {
    const stream = createControlledResponse([conversationEvent + runEvent])
    let streamSignal: AbortSignal | undefined
    vi.stubGlobal('fetch', vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      streamSignal = init?.signal || undefined
      stream.bindSignal(streamSignal)
      return Promise.resolve(stream.response)
    }))
    const view = renderChat()
    await sendChapterRequest()

    view.unmount()
    expect(streamSignal?.aborted).toBe(true)
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('restores a persisted running task after reload and cancels its operation', async () => {
    mockGet.mockImplementation((url: string) => {
      if (url === '/projects/project-1/ai/assistant/conversations') {
        return Promise.resolve({
          data: { data: { items: [{ id: 'conversation-restored', project_id: 'project-1', title: '后台写章' }], total: 1 } },
        })
      }
      if (url === '/projects/project-1/ai/assistant/conversations/conversation-restored') {
        return Promise.resolve({
          data: {
            data: {
              conversation: { id: 'conversation-restored', project_id: 'project-1', title: '后台写章' },
              messages: [
                {
                  id: 'user-restored', conversation_id: 'conversation-restored', role: 'user',
                  content: '写第一章', status: 'completed',
                },
                {
                  id: 'assistant-restored', conversation_id: 'conversation-restored', role: 'assistant',
                  content: '正在写作', status: 'running',
                  payload: {
                    reply: '正在写作', tool_logs: [], actions: [], applied_actions: [],
                    run: { id: 'run-restored', operation_id: 'operation-restored', status: 'running' },
                  },
                },
              ],
            },
          },
        })
      }
      if (url === '/projects/project-1/ai/assistant/runs/run-restored') {
        return Promise.resolve({
          data: {
            data: {
              run: { id: 'run-restored', operation_id: 'operation-restored', status: 'running' },
              steps: [],
            },
          },
        })
      }
      return Promise.reject(new Error(`unexpected GET ${url}`))
    })
    vi.stubGlobal('fetch', vi.fn((_input: RequestInfo | URL, init?: RequestInit) => (
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true })
      })
    )))

    const user = userEvent.setup()
    renderChat()

    await user.click(await screen.findByRole('button', { name: '取消当前任务' }))
    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/operations/operation-restored/cancel')
    })
    expect(within(screen.getByTestId('project-ai-chat')).getByRole('status')).toHaveTextContent('已停止后续执行')
  })

  it('converges a restored running task to its persisted completed message', async () => {
    mockGet.mockImplementation((url: string) => {
      if (url === '/projects/project-1/ai/assistant/conversations') {
        return Promise.resolve({
          data: { data: { items: [{ id: 'conversation-1', project_id: 'project-1', title: '第一章' }], total: 1 } },
        })
      }
      if (url === '/projects/project-1/ai/assistant/conversations/conversation-1') {
        return Promise.resolve({
          data: {
            data: {
              conversation: { id: 'conversation-1', project_id: 'project-1', title: '第一章' },
              messages: [{
                id: 'assistant-1', conversation_id: 'conversation-1', role: 'assistant', content: '正在写作', status: 'running',
                payload: {
                  reply: '正在写作', tool_logs: [], actions: [], applied_actions: [],
                  run: { id: 'run-1', operation_id: 'operation-1', status: 'running' },
                },
              }],
            },
          },
        })
      }
      if (url === '/projects/project-1/ai/assistant/runs/run-1') {
        return Promise.resolve({
          data: { data: { run: { id: 'run-1', operation_id: 'operation-1', status: 'running' }, steps: [] } },
        })
      }
      return Promise.reject(new Error(`unexpected GET ${url}`))
    })
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({
      ok: true,
      status: 200,
      json: async () => completedRunDetail,
    } as Response)))

    const { onApplied } = renderChat()

    expect(await screen.findByText('正文已保存')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: /发送/ })).toBeInTheDocument())
    expect(onApplied).toHaveBeenCalledTimes(1)
  })

  it('renders conversation selection and deletion as sibling buttons', async () => {
    mockGet.mockImplementation((url: string) => {
      if (url === '/projects/project-1/ai/assistant/conversations') {
        return Promise.resolve({
          data: { data: { items: [{ id: 'conversation-old', project_id: 'project-1', title: '旧对话' }], total: 1 } },
        })
      }
      return Promise.resolve({
        data: {
          data: {
            conversation: { id: 'conversation-old', project_id: 'project-1', title: '旧对话' },
            messages: [],
          },
        },
      })
    })
    renderChat()

    const selectButton = await screen.findByRole('button', { name: '旧对话' })
    const deleteButton = screen.getByRole('button', { name: '删除对话：旧对话' })
    expect(selectButton.contains(deleteButton)).toBe(false)
    expect(deleteButton.parentElement).toBe(selectButton.parentElement)
  })
})
