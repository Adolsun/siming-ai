import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { message } from 'antd'

const { mockGet, mockPost, mockPatch, mockDelete, mockNavigate, modelState } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockPatch: vi.fn(),
  mockDelete: vi.fn(),
  mockNavigate: vi.fn(),
  modelState: { defaultModel: 'openai:test' },
}))

vi.mock('../api/client', () => ({
  apiClient: { get: mockGet, post: mockPost, patch: mockPatch, delete: mockDelete },
}))

vi.mock('../hooks/useModelOptions', () => ({
  useModelOptions: () => ({
    defaultModel: modelState.defaultModel,
    loading: false,
    modelOptions: [
      { value: 'openai:test', label: 'OpenAI · test', provider: 'openai', model: 'test' },
      { value: 'anthropic:sonnet', label: 'Anthropic Claude · sonnet', provider: 'anthropic', model: 'sonnet' },
    ],
  }),
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

import GuiAssistantChat from '../components/GuiAssistantChat'

describe('GuiAssistantChat new-book handoff', () => {
  afterEach(() => {
    message.destroy()
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  beforeEach(() => {
    vi.clearAllMocks()
    modelState.defaultModel = 'openai:test'
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() })
    mockGet.mockImplementation((url: string) => {
      if (url === '/projects') return Promise.resolve({ data: { data: { items: [], total: 0 } } })
      if (url === '/ai/system-assistant/conversations') return Promise.resolve({ data: { data: { items: [], total: 0 } } })
      if (url === '/novel-creation/sessions/session-1/artifacts') return Promise.resolve({ data: { data: {
        revision: 7,
        artifacts: [
          {
            artifact: 'concepts',
            label: '创意方案',
            status: 'generated',
            source: 'model',
            revision: 7,
            locked_paths: [],
            can_undo: true,
            checkpoint_count: 1,
            version_count: 2,
            latest_version_id: 'version-new',
            flow: { can_view: true, can_generate: true, can_confirm: true, blocked_by: [], soft_dependencies: [] },
          },
          {
            artifact: 'characters',
            label: '角色与关系',
            status: 'stale',
            source: 'assistant',
            revision: 7,
            stale_reason: '上游创意方案已修改',
            locked_paths: ['/characters/0'],
            flow: {
              can_view: true,
              can_generate: true,
              can_confirm: false,
              blocked_by: [],
              soft_dependencies: [{ stage: 'world_style', label: '文风与世界观', reason: 'not_confirmed', message: '仍可生成' }],
            },
          },
        ],
      } } })
      if (url === '/novel-creation/sessions/session-1/artifacts/concepts/versions') {
        return Promise.resolve({ data: { data: { versions: [
          {
            id: 'version-new', session_id: 'session-1', artifact: 'concepts', revision: 7,
            status: 'generated', source: 'assistant', change_type: 'patch', parent_version_id: 'version-old',
            created_at: '2026-08-02T12:00:00Z',
          },
          {
            id: 'version-old', session_id: 'session-1', artifact: 'concepts', revision: 5,
            status: 'generated', source: 'model', change_type: 'generate', parent_version_id: null,
            created_at: '2026-08-02T11:00:00Z',
          },
        ] } } })
      }
      if (url === '/novel-creation/artifact-versions/version-new') {
        return Promise.resolve({ data: { data: {
          version: { id: 'version-new', revision: 7 },
          against: { id: 'version-old', revision: 5 },
          changes: [{ path: '/concepts/0/title', action: 'replace', before: '旧方案', after: '新方案' }],
          change_count: 1,
          truncated: false,
        } } })
      }
      if (url === '/novel-creation/artifact-versions/version-old') {
        return Promise.resolve({ data: { data: {
          version: { id: 'version-old', revision: 5 },
          against: null,
          changes: [{ path: '/concepts', action: 'add', after: [{ title: '旧方案' }] }],
          change_count: 1,
          truncated: false,
        } } })
      }
      return Promise.reject(new Error(`unexpected GET ${url}`))
    })
    mockPost.mockImplementation((url: string) => {
      if (url === '/novel-creation/start') return Promise.resolve({ data: { data: { session_id: 'session-1' } } })
      if (url === '/novel-creation/sessions/session-1/interview/next') {
        return Promise.resolve({
          data: {
            data: {
              session_id: 'session-1',
              state: 'ready',
              history: [],
              runtime: {
                effective_model: 'openai:test',
                provider: 'openai',
                model_source: 'global_default',
                tool_mode: 'api_text_json',
                timeout_seconds: 30,
                quota_status: 'unknown',
              },
            },
          },
        })
      }
      if (url === '/novel-creation/sessions/session-1/runs') {
        return Promise.resolve({ data: { data: { run: {
          id: 'run-1',
          session_id: 'session-1',
          stage: 'concepts',
          status: 'running',
          operation_id: 'operation-1',
          current_message: '正在生成创意方向',
        } } } })
      }
      if (url === '/novel-creation/conversation-command') {
        return Promise.resolve({ data: { data: {
          summary: '已开始角色与关系调整',
          run: {
            id: 'run-characters',
            session_id: 'session-1',
            stage: 'characters',
            status: 'running',
            operation_id: 'operation-characters',
            current_message: '正在调整角色与关系',
          },
        } } })
      }
      if (url === '/novel-creation/sessions/session-1/stages/concepts/confirm') {
        return Promise.resolve({ data: { data: { id: 'session-1', revision: 8 } } })
      }
      if (url === '/novel-creation/sessions/session-1/artifacts/concepts/undo') {
        return Promise.resolve({ data: { data: { artifact: { artifact: 'concepts', revision: 8 } } } })
      }
      if (url === '/novel-creation/artifact-versions/version-old/restore') {
        return Promise.resolve({ data: { data: { artifact: { artifact: 'concepts', revision: 8 } } } })
      }
      if (url === '/ai/system-assistant/conversations') {
        return Promise.resolve({ data: { data: { conversation: { id: 'conversation-1', title: '新书' } } } })
      }
      if (url === '/ai/system-assistant/conversations/conversation-1/turns') {
        return Promise.resolve({ data: { data: { conversation: { id: 'conversation-1', title: '新书' } } } })
      }
      return Promise.reject(new Error(`unexpected POST ${url}`))
    })
    mockPatch.mockResolvedValue({ data: { data: {} } })
  })

  it('persists project assistant turns in the canonical project-scoped conversation', async () => {
    localStorage.setItem('siming.gui.assistant.projectId', 'project-1')
    mockGet.mockImplementation((url: string) => {
      if (url === '/projects') {
        return Promise.resolve({ data: { data: { items: [{ id: 'project-1', title: '测试作品' }], total: 1 } } })
      }
      if (url === '/ai/system-assistant/conversations') {
        return Promise.resolve({ data: { data: { items: [], total: 0 } } })
      }
      return Promise.reject(new Error(`unexpected GET ${url}`))
    })
    mockPost.mockImplementation((url: string, body: any) => {
      if (url === '/ai/system-assistant/conversations') {
        expect(body).toMatchObject({ scope_type: 'project', scope_id: 'project-1' })
        return Promise.resolve({ data: { data: { conversation: { id: 'project-conversation-1', title: '讨论' } } } })
      }
      if (url === '/ai/system-assistant/conversations/project-conversation-1/turns/start') {
        expect(body).toMatchObject({ scope_type: 'project', scope_id: 'project-1', user_content: '调整主角动机' })
        return Promise.resolve({ data: { data: {
          conversation: { id: 'project-conversation-1', title: '讨论', scope_type: 'project', scope_id: 'project-1' },
          messages: [{ id: 'user-1' }, { id: 'assistant-1' }],
        } } })
      }
      return Promise.reject(new Error(`unexpected POST ${url}`))
    })
    const stream = [
      'data: ' + JSON.stringify({ type: 'complete', data: { reply: '已调整主角动机', run: { id: 'run-1', operation_id: 'operation-1' } } }),
      'data: [DONE]',
      '',
    ].join('\n\n')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(stream, {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    })))

    const user = userEvent.setup()
    render(<MemoryRouter><GuiAssistantChat /></MemoryRouter>)
    await waitFor(() => expect(screen.getByText(/作品模式/)).toBeInTheDocument())
    await user.type(screen.getByRole('textbox', { name: '给司命的消息' }), '调整主角动机')
    await user.click(screen.getByRole('button', { name: /发送/ }))

    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith(
      '/ai/system-assistant/conversations/project-conversation-1/turns/assistant-1',
      expect.objectContaining({
        assistant_content: '已调整主角动机',
        status: 'completed',
        scope_type: 'project',
        scope_id: 'project-1',
        run_id: 'run-1',
        operation_id: 'operation-1',
      }),
    ))
  })

  it('offers the free setup flow when no model is configured', async () => {
    modelState.defaultModel = ''
    const user = userEvent.setup()
    render(<MemoryRouter><GuiAssistantChat /></MemoryRouter>)

    expect(await screen.findByText('还差一步：先连接一个模型')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '免费设置' }))
    expect(mockNavigate).toHaveBeenCalledWith('/getting-started')
  })

  it('hands a completed interview to a compact concept run instead of drafting full blueprints', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter><GuiAssistantChat /></MemoryRouter>)

    await user.type(await screen.findByRole('textbox', { name: '给司命的消息' }), '我要创建新的小说')
    await user.click(screen.getByRole('button', { name: /发送/ }))

    expect(await screen.findByText('立项任务')).toBeInTheDocument()
    expect(screen.getByText('正在生成创意方向')).toBeInTheDocument()
    expect(mockNavigate).not.toHaveBeenCalledWith('/novel-creation?session=session-1&run=run-1')
    expect(mockPost).toHaveBeenCalledWith('/novel-creation/sessions/session-1/interview/next', expect.objectContaining({
      qa_history: [],
    }), { timeout: 0 })
    expect(mockPost).toHaveBeenCalledWith('/novel-creation/sessions/session-1/runs', expect.objectContaining({
      stage: 'concepts',
      operation: 'generate',
    }))
    expect(mockPost).not.toHaveBeenCalledWith('/novel-creation/draft', expect.anything())
  })

  it('keeps structured creation data visible beside the conversation and confirms it in place', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter><GuiAssistantChat /></MemoryRouter>)

    await user.type(await screen.findByRole('textbox', { name: '给司命的消息' }), '我要创建新的小说')
    await user.click(screen.getByRole('button', { name: /发送/ }))

    expect(await screen.findByRole('complementary', { name: '立项数据' })).toBeInTheDocument()
    expect(await screen.findByText('角色与关系')).toBeInTheDocument()
    expect(screen.getByText('上游创意方案已修改')).toBeInTheDocument()
    expect(screen.getByText('已锁定 1 项')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '确认创意方案' }))
    expect(mockPost).toHaveBeenCalledWith('/novel-creation/sessions/session-1/stages/concepts/confirm', {
      confirm: true,
      source: 'author',
      expected_revision: 7,
    })

    await user.click(screen.getByRole('button', { name: '撤销创意方案最近一次修改' }))
    expect(mockPost).toHaveBeenCalledWith('/novel-creation/sessions/session-1/artifacts/concepts/undo', {
      expected_revision: 7,
    })
  })

  it('shows immutable artifact history, compares revisions, and restores with revision protection', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter><GuiAssistantChat /></MemoryRouter>)

    await user.type(await screen.findByRole('textbox', { name: '\u7ed9\u53f8\u547d\u7684\u6d88\u606f' }), '\u6211\u8981\u521b\u5efa\u65b0\u7684\u5c0f\u8bf4')
    await user.click(screen.getByRole('button', { name: /\u53d1\u9001/ }))

    await user.click(await screen.findByRole('button', { name: '\u67e5\u770b\u521b\u610f\u65b9\u6848\u7248\u672c\u5386\u53f2' }))
    expect(await screen.findByRole('dialog', { name: /\u7248\u672c\u5386\u53f2/ })).toBeInTheDocument()
    expect(await screen.findByText('/concepts/0/title')).toBeInTheDocument()
    expect(mockGet).toHaveBeenCalledWith('/novel-creation/artifact-versions/version-new')

    await user.click(screen.getAllByRole('listitem')[1])
    expect(await screen.findByText('/concepts')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /\u6062\u590d\u6b64\u7248\u672c/ }))

    expect(mockPost).toHaveBeenCalledWith('/novel-creation/artifact-versions/version-old/restore', {
      expected_revision: 7,
    })
  })

  it('makes the current conversation model visible', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter><GuiAssistantChat /></MemoryRouter>)

    await user.click(await screen.findByRole('button', { name: '查看当前模型与运行状态' }))
    expect(await screen.findByRole('combobox', { name: '选择本次对话模型' })).toBeInTheDocument()
    expect(screen.getByText('OpenAI · test')).toBeInTheDocument()
  })

  it('starts a targeted artifact refinement from chat without opening the workbench', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter><GuiAssistantChat /></MemoryRouter>)

    const input = await screen.findByRole('textbox', { name: '给司命的消息' })
    await user.type(input, '我要创建一本新的小说')
    await user.click(screen.getByRole('button', { name: /发送/ }))
    expect(await screen.findByText('立项任务')).toBeInTheDocument()

    await user.type(input, '主角保持不变，重做反派和人物关系')
    await user.click(screen.getByRole('button', { name: /发送/ }))

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/novel-creation/conversation-command', expect.objectContaining({
        session_id: 'session-1',
        stage: 'characters',
        action: 'refine_artifact',
      }))
    })
    expect(screen.getByText('正在调整角色与关系')).toBeInTheDocument()
    expect(mockNavigate).not.toHaveBeenCalledWith(expect.stringContaining('/novel-creation'))
  })

  it('shows actual runtime diagnostics after an interview response', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter><GuiAssistantChat /></MemoryRouter>)

    await user.type(await screen.findByRole('textbox', { name: '给司命的消息' }), '\u6211\u60f3\u521b\u5efa\u4e00\u672c\u65b0\u7684\u5c0f\u8bf4')
    await user.click(screen.getByRole('button', { name: /\u53d1\u9001/ }))

    await user.click(screen.getByRole('button', { name: '\u67e5\u770b\u5f53\u524d\u6a21\u578b\u4e0e\u8fd0\u884c\u72b6\u6001' }))
    await waitFor(() => {
      const runtime = screen.getByLabelText('\u5f53\u524d\u6a21\u578b\u8fd0\u884c\u72b6\u6001')
      expect(runtime).toHaveTextContent('\u63d0\u4f9b\u5546')
      expect(runtime).toHaveTextContent('openai')
      expect(runtime).toHaveTextContent('openai:test')
      expect(runtime).toHaveTextContent('\u5168\u5c40\u9ed8\u8ba4')
      expect(runtime).toHaveTextContent('\u52a8\u6001\u91c7\u8bbf JSON')
      expect(runtime).toHaveTextContent('30 \u79d2')
    })
  })

  it('marks a failed system chat as an error instead of a completion', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter><GuiAssistantChat /></MemoryRouter>)

    await user.type(await screen.findByRole('textbox', { name: '给司命的消息' }), '你好')
    await user.click(screen.getByRole('button', { name: /发送/ }))

    const errorMessage = await screen.findByRole('alert')
    expect(errorMessage).toHaveAttribute('data-message-status', 'error')
    expect(errorMessage).toHaveTextContent('unexpected POST /novel-creation/system-chat')
  })

  it('marks an empty system chat reply as an error instead of a completion', async () => {
    mockPost.mockImplementation((url: string) => {
      if (url === '/novel-creation/system-chat') return Promise.resolve({ data: { data: { reply: '' } } })
      return Promise.reject(new Error(`unexpected POST ${url}`))
    })
    const user = userEvent.setup()
    render(<MemoryRouter><GuiAssistantChat /></MemoryRouter>)

    await user.type(await screen.findByRole('textbox', { name: '给司命的消息' }), '你好')
    await user.click(screen.getByRole('button', { name: /发送/ }))

    const errorMessage = await screen.findByRole('alert')
    expect(errorMessage).toHaveAttribute('data-message-status', 'error')
    expect(errorMessage).toHaveTextContent('当前模型没有返回文字回复')
  })

  it('marks a failed interview skip as an error instead of a completion', async () => {
    mockPost.mockImplementation((url: string) => {
      if (url === '/novel-creation/start') return Promise.resolve({ data: { data: { session_id: 'session-1' } } })
      if (url === '/novel-creation/sessions/session-1/interview/next') {
        const priorCalls = mockPost.mock.calls.filter(([calledUrl]) => calledUrl === url).length
        if (priorCalls === 1) {
          return Promise.resolve({
            data: {
              data: {
                session_id: 'session-1',
                state: 'question',
                question: { question: '主角最想得到什么？', type: 'choice', options: ['自由'] },
                history: [],
              },
            },
          })
        }
        return Promise.reject(new Error('模型额度已耗尽'))
      }
      return Promise.reject(new Error(`unexpected POST ${url}`))
    })

    const user = userEvent.setup()
    render(<MemoryRouter><GuiAssistantChat /></MemoryRouter>)

    await user.type(await screen.findByRole('textbox', { name: '给司命的消息' }), '我想创建一本新的小说')
    await user.click(screen.getByRole('button', { name: /发送/ }))
    await user.click(await screen.findByRole('button', { name: '跳过并生成创意方向' }))

    const errorMessage = await screen.findByRole('alert')
    expect(errorMessage).toHaveAttribute('data-message-status', 'error')
    expect(errorMessage).toHaveTextContent('模型额度已耗尽')
    expect(errorMessage).toHaveTextContent('执行失败')
    expect(screen.queryByText('主角最想得到什么？')).not.toBeInTheDocument()
  })

  it('renders quota exhaustion as an error with the actual CLI diagnostics', async () => {
    let interviewCalls = 0
    mockPost.mockImplementation((url: string) => {
      if (url === '/novel-creation/start') return Promise.resolve({ data: { data: { session_id: 'session-1' } } })
      if (url === '/novel-creation/sessions/session-1/interview/next') {
        interviewCalls += 1
        if (interviewCalls === 1) {
          return Promise.resolve({
            data: {
              data: {
                session_id: 'session-1',
                state: 'question',
                question: { question: '\u5f00\u5c40\u7684\u4ee3\u4ef7\u662f\u4ec0\u4e48\uff1f', type: 'text' },
                history: [],
              },
            },
          })
        }
        return Promise.reject({
          response: {
            data: {
              detail: {
                message: 'Free usage exceeded, retrying in 9h',
                failure_class: 'quota_or_rate_limit',
                next_action: '\u5207\u6362\u6709\u989d\u5ea6\u7684\u6a21\u578b\u540e\u91cd\u8bd5\u3002',
                runtime: {
                  effective_model: 'opencode_cli:free-model',
                  provider: 'opencode_cli',
                  model_source: 'conversation_override',
                  tool_mode: 'local_cli_text_json',
                  timeout_seconds: 45,
                  quota_status: 'exhausted_or_limited',
                },
              },
            },
          },
        })
      }
      return Promise.reject(new Error(`unexpected POST ${url}`))
    })

    const user = userEvent.setup()
    render(<MemoryRouter><GuiAssistantChat /></MemoryRouter>)

    await user.type(await screen.findByRole('textbox', { name: '给司命的消息' }), '\u6211\u60f3\u521b\u5efa\u4e00\u672c\u65b0\u7684\u5c0f\u8bf4')
    await user.click(screen.getByRole('button', { name: /\u53d1\u9001/ }))
    await user.click(await screen.findByRole('button', { name: '\u8df3\u8fc7\u5e76\u751f\u6210\u521b\u610f\u65b9\u5411' }))

    await user.click(screen.getByRole('button', { name: '\u67e5\u770b\u5f53\u524d\u6a21\u578b\u4e0e\u8fd0\u884c\u72b6\u6001' }))
    await waitFor(() => {
      const errorMessage = screen.getByRole('alert')
      expect(errorMessage).toHaveAttribute('data-message-status', 'error')
      expect(errorMessage).toHaveTextContent('Free usage exceeded')
      expect(screen.getByLabelText('\u5f53\u524d\u6a21\u578b\u8fd0\u884c\u72b6\u6001')).toHaveTextContent('\u5df2\u8017\u5c3d\u6216\u9650\u6d41')
      expect(screen.getByLabelText('\u5f53\u524d\u6a21\u578b\u8fd0\u884c\u72b6\u6001')).toHaveTextContent('opencode_cli:free-model')
      expect(screen.getByLabelText('\u5f53\u524d\u6a21\u578b\u8fd0\u884c\u72b6\u6001')).toHaveTextContent('45 \u79d2')
    })
  })

  it('uploads creation material as a durable binary import and applies a selected preview', async () => {
    mockGet.mockImplementation((url: string) => {
      if (url === '/projects') return Promise.resolve({ data: { data: { items: [], total: 0 } } })
      if (url === '/ai/system-assistant/conversations') return Promise.resolve({ data: { data: { items: [], total: 0 } } })
      if (url === '/novel-creation/sessions/session-1/imports') return Promise.resolve({ data: { data: { imports: [] } } })
      if (url === '/novel-creation/sessions/session-1/artifacts') return Promise.resolve({ data: { data: { artifacts: [{ artifact: 'characters', label: '角色与关系', status: 'pending', revision: 1 }] } } })
      if (url === '/novel-creation/imports/import-1') return Promise.resolve({ data: { data: {
        id: 'import-1', source_file_id: 'import-1', session_id: 'session-1', operation_id: 'operation-import-1',
        filename: '八卷大纲.md', status: 'waiting_user', text_length: 32000, chunk_count: 5, processed_chunks: 5, input_revision: 1,
        preview: {
          detected: { characters: 12, factions: 4, locations: 19, volumes: 8, chapter_summaries: 146 },
          artifact_counts: { characters: 12, locations: 23, macro_outline: 8, opening_outline: 146 },
          available_artifacts: ['characters', 'locations', 'macro_outline', 'opening_outline'],
          conflicts: [{ kind: 'existing_artifact', artifact: 'characters', status: 'generated' }],
        },
      } } })
      return Promise.reject(new Error(`unexpected GET ${url}`))
    })
    mockPost.mockImplementation((url: string) => {
      if (url === '/novel-creation/start') return Promise.resolve({ data: { data: { session_id: 'session-1' } } })
      if (url === '/novel-creation/sessions/session-1/imports') return Promise.resolve({ data: { data: {
        id: 'import-1', source_file_id: 'import-1', session_id: 'session-1', operation_id: 'operation-import-1',
        filename: '八卷大纲.md', status: 'running', text_length: 0, chunk_count: 0, processed_chunks: 0, input_revision: 1,
      } } })
      if (url === '/novel-creation/imports/import-1/apply') return Promise.resolve({ data: { data: {
        applied: [{ artifact: 'characters', count: 12 }, { artifact: 'macro_outline', count: 8 }], skipped: [], revision: 3,
      } } })
      return Promise.reject(new Error(`unexpected POST ${url}`))
    })

    const user = userEvent.setup()
    const { container } = render(<MemoryRouter><GuiAssistantChat /></MemoryRouter>)
    const upload = await waitFor(() => container.querySelector('input[type="file"]') as HTMLInputElement)
    const file = new File(['# 第一卷\n卷纲内容'], '八卷大纲.md', { type: 'text/markdown' })
    await user.upload(upload, file)
    expect((await screen.findAllByText(/八卷大纲.md/)).length).toBeGreaterThan(0)
    await user.click(screen.getByRole('button', { name: /发送/ }))

    expect(await screen.findByText('资料导入')).toBeInTheDocument()
    expect(await screen.findByText('卷纲 8')).toBeInTheDocument()
    expect(await screen.findByText('导入预览 · 八卷大纲.md')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '应用所选数据' }))
    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/novel-creation/imports/import-1/apply', expect.objectContaining({
        selected_artifacts: expect.arrayContaining(['characters', 'macro_outline']),
        strategy: 'merge',
        expected_revision: 1,
      }))
    })
    expect(await screen.findByText(/导入已完成/)).toBeInTheDocument()
  })
})
