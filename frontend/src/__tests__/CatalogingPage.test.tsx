import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn(), patch: vi.fn(), post: vi.fn(), stream: vi.fn() }))
vi.mock('../api/client', () => ({ apiClient: api }))
vi.mock('../hooks/useModelOptions', () => ({
  useModelOptions: () => ({ defaultModel: 'openai:test', loading: false, modelOptions: [] }),
}))

import CatalogingPage from '../pages/CatalogingPage'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((next) => { resolve = next })
  return { promise, resolve }
}

function job(id: string, model: string) {
  return {
    id,
    project_id: 'project-1',
    status: 'running',
    execution_mode: 'auto',
    model,
    effective_model: model,
    model_source: 'task',
    provider: 'openai',
    total_chapters: 1,
    completed_chapters: 0,
    failed_chapters: 0,
    current_chapter_id: `chapter-${id}`,
    blocked_chapter_id: null,
    error: null,
  }
}

function run(id: string, jobId: string, title: string) {
  return {
    id,
    job_id: jobId,
    chapter_id: `chapter-${jobId}`,
    chapter_order: 1,
    chapter_title: title,
    status: 'running',
  }
}

describe('CatalogingPage job ownership', () => {
  beforeEach(() => {
    Object.values(api).forEach((mock) => mock.mockReset())
    api.stream.mockImplementation(() => undefined)
  })

  it('opens the linked task outside loaded history, observes it, and releases a hidden page', async () => {
    const selected = job('linked-job', 'linked-model')
    api.stream.mockImplementation(() => vi.fn())
    api.get.mockImplementation((url: string) => {
      if (url.endsWith('/cataloging/linked-job')) return Promise.resolve({ data: { data: { job: selected, runs: [run('linked-run', selected.id, '链接章节')] } } })
      return Promise.resolve({ data: { data: { items: [], total: 0 } } })
    })
    const view = render(<CatalogingPage projectId="project-1" focusJobId="linked-job" />)
    expect(screen.getByRole('status')).toHaveTextContent('正在加载建档进度')
    await waitFor(() => expect(api.stream).toHaveBeenCalledOnce())
    expect(api.stream.mock.calls[0][0]).toBe('/projects/project-1/cataloging/linked-job/stream')
    expect(screen.getByText('linked-model · task')).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
    view.rerender(<CatalogingPage projectId="project-1" focusJobId="linked-job" active={false} />)
    expect(api.stream.mock.results[0].value).toHaveBeenCalledOnce()
    await act(async () => { api.stream.mock.calls[0][2](JSON.stringify({ type: 'failed', job: { ...selected, status: 'failed', error: '隐藏页旧事件' } })) })
    expect(screen.queryByText('隐藏页旧事件')).not.toBeInTheDocument()
    view.rerender(<CatalogingPage projectId="project-1" focusJobId="linked-job" />)
    await waitFor(() => expect(api.stream).toHaveBeenCalledTimes(2))
    expect(api.post).not.toHaveBeenCalled()
  })

  it('shows a failed link load and retries that exact task without selecting history', async () => {
    api.get.mockImplementation((url: string) => url.endsWith('/cataloging/missing')
      ? Promise.reject(new Error('作品建档任务不存在'))
      : Promise.resolve({ data: { data: { items: [], total: 0 } } }))
    render(<CatalogingPage projectId="project-1" focusJobId="missing" />)
    expect(await screen.findByText('无法加载建档进度')).toBeInTheDocument()
    expect(screen.getByText('作品建档任务不存在')).toBeInTheDocument()
    expect(api.stream).not.toHaveBeenCalled()
    api.get.mockImplementation((url: string) => url.endsWith('/cataloging/missing')
      ? Promise.resolve({ data: { data: { job: job('missing', 'retry-model'), runs: [] } } })
      : Promise.resolve({ data: { data: { items: [], total: 0 } } }))
    fireEvent.click(screen.getByRole('button', { name: '重新加载进度' }))
    await waitFor(() => expect(api.stream).toHaveBeenCalledOnce())
    expect(screen.getByText('retry-model · task')).toBeInTheDocument()
  })

  it('cancels a previous linked task request and never observes its late response', async () => {
    const old = deferred<any>()
    api.get.mockImplementation((url: string) => {
      if (url.endsWith('/cataloging/job-a')) return old.promise
      if (url.endsWith('/cataloging/job-b')) return Promise.resolve({ data: { data: { job: job('job-b', '最新任务'), runs: [] } } })
      return Promise.resolve({ data: { data: { items: [], total: 0 } } })
    })
    const view = render(<CatalogingPage projectId="project-1" focusJobId="job-a" />)
    const oldSignal = api.get.mock.calls.find(call => call[0].endsWith('/cataloging/job-a'))![2].signal
    view.rerender(<CatalogingPage projectId="project-1" focusJobId="job-b" />)
    expect(oldSignal.aborted).toBe(true)
    await waitFor(() => expect(api.stream).toHaveBeenCalledOnce())
    await act(async () => { old.resolve({ data: { data: { job: job('job-a', '迟到任务'), runs: [] } } }); await old.promise })
    expect(screen.getByText('最新任务 · task')).toBeInTheDocument()
    expect(screen.queryByText('迟到任务 · task')).not.toBeInTheDocument()
    expect(api.stream).toHaveBeenCalledOnce()
  })

  it('retains the last completed chapter records after the stream terminal event', async () => {
    const completed = { ...job('done', 'done-model'), status: 'completed', completed_chapters: 1,
      current_chapter_id: null, last_completed_chapter_id: 'chapter-done' }
    const completedRun = { ...run('done-run', 'done', '完成章节'), status: 'completed' }
    const candidate = { id: 'done-candidate', chapter_id: 'chapter-done', chapter_run_id: 'done-run',
      item_type: 'chapter_summary', status: 'applied', payload: { summary_text: '保存的章节总结' } }
    api.get.mockImplementation((url: string) => {
      if (url.endsWith('/cataloging/done')) return Promise.resolve({ data: { data: { job: completed, runs: [completedRun] } } })
      if (url.endsWith('/candidates')) return Promise.resolve({ data: { data: { items: [candidate], total: 1 } } })
      return Promise.resolve({ data: { data: { items: [], total: 0 } } })
    })
    render(<CatalogingPage projectId="project-1" focusJobId="done" />)
    await waitFor(() => expect(api.stream).toHaveBeenCalledOnce())
    expect(api.get).toHaveBeenCalledWith('/projects/project-1/cataloging/done/candidates', { chapter_run_id: 'done-run' }, expect.objectContaining({ timeout: 15000 }))
    const before = screen.getByDisplayValue(/保存的章节总结/)
    await act(async () => { api.stream.mock.calls[0][2](JSON.stringify({ type: 'completed', job: completed })) })
    expect(before).toBeInTheDocument()
  })

  it('upserts durable facts on reconnect and ignores events from a replaced connection', async () => {
    const active = job('job-a', 'model-a')
    const activeRun = run('run-a', 'job-a', '当前章节')
    const fact = { id: 'fact-1', job_id: active.id, chapter_run_id: activeRun.id,
      chapter_id: activeRun.chapter_id, fact_type: 'chapter_overview', payload: { summary: '已有事实' }, status: 'active' }
    api.stream.mockImplementation(() => vi.fn())
    api.get.mockImplementation((url: string) => {
      if (url.endsWith('/chapters')) return Promise.resolve({ data: { data: { items: [], total: 0 } } })
      if (url.endsWith('/cataloging/jobs')) return Promise.resolve({ data: { data: { items: [active], total: 1 } } })
      if (url.endsWith('/cataloging/job-a')) return Promise.resolve({ data: { data: { job: active, runs: [activeRun] } } })
      if (url.endsWith('/facts')) return Promise.resolve({ data: { data: { items: [fact], total: 1 } } })
      if (url.endsWith('/candidates')) return Promise.resolve({ data: { data: { items: [], total: 0 } } })
      return Promise.reject(new Error(`unexpected GET ${url}`))
    })
    const view = render(<CatalogingPage projectId="project-1" />)
    fireEvent.click(await screen.findByRole('button', { name: '载入任务' }))
    expect(await screen.findByText('已保存 1 条事实 · 0 条候选')).toBeInTheDocument()
    await waitFor(() => expect(api.stream).toHaveBeenCalledOnce())
    const firstCallback = api.stream.mock.calls[0][2]
    const firstError = api.stream.mock.calls[0][3]
    await act(async () => {
      firstCallback(JSON.stringify({ type: 'fact_extracted', fact, run: activeRun, job: active }))
      firstCallback(JSON.stringify({ type: 'fact_extracted', fact, run: activeRun, job: active }))
    })
    expect(screen.getByText('已保存 1 条事实 · 0 条候选')).toBeInTheDocument()
    await act(async () => { firstError(new Error('连接中断')) })
    fireEvent.click(screen.getByRole('button', { name: '查看实时进度' }))
    expect(api.stream.mock.results[0].value).toHaveBeenCalledOnce()
    await act(async () => {
      firstCallback(JSON.stringify({ type: 'failed', job: { ...active, status: 'failed', error: '旧连接迟到的错误' } }))
      firstError(new Error('旧连接错误'))
      api.stream.mock.calls[1][2](JSON.stringify({ type: 'fact_extracted', fact, run: activeRun, job: active }))
    })
    expect(screen.queryByText('旧连接迟到的错误')).not.toBeInTheDocument()
    expect(screen.getByText('已保存 1 条事实 · 0 条候选')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '暂停任务' })).toBeInTheDocument()
    view.unmount()
    expect(api.stream.mock.results[1].value).toHaveBeenCalledOnce()
  })

  it('loads history beyond twenty tasks without changing the selected task', async () => {
    const jobs = Array.from({ length: 21 }, (_, index) => job(`history-${index}`, `model-${index}`))
    api.get.mockImplementation((url: string, params?: { offset?: number }) => {
      if (url.endsWith('/chapters')) return Promise.resolve({ data: { data: { items: [], total: 0 } } })
      if (url.endsWith('/cataloging/jobs')) {
        const offset = params?.offset || 0
        return Promise.resolve({ data: { data: {
          items: jobs.slice(offset, offset + 20), total: 21, next_offset: offset === 0 ? 20 : null,
        } } })
      }
      if (url.endsWith('/cataloging/history-0')) {
        return Promise.resolve({ data: { data: { job: jobs[0], runs: [run('history-run', 'history-0', '已选择章节')] } } })
      }
      if (url.endsWith('/candidates') || url.endsWith('/facts')) {
        return Promise.resolve({ data: { data: { items: [], total: 0 } } })
      }
      return Promise.reject(new Error(`unexpected GET ${url}`))
    })
    render(<CatalogingPage projectId="project-1" />)
    const firstPage = await screen.findAllByRole('button', { name: '载入任务' })
    expect(firstPage).toHaveLength(20)
    fireEvent.click(firstPage[0])
    expect(await screen.findByText('model-0 · task')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '加载更早任务' }))
    expect(await screen.findByText('已显示 21 / 21 条任务')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: '载入任务' })).toHaveLength(21)
    expect(screen.queryByRole('button', { name: '加载更早任务' })).not.toBeInTheDocument()
    expect(screen.getByText('model-0 · task')).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/projects/project-1/cataloging/jobs', { limit: 20, offset: 20 })
  })

  it('does not mix an older job response into the last selected task', async () => {
    const first = deferred<{ data: { data: { job: ReturnType<typeof job>; runs: ReturnType<typeof run>[] } } }>()
    const second = deferred<{ data: { data: { job: ReturnType<typeof job>; runs: ReturnType<typeof run>[] } } }>()
    const jobs = [job('job-a', 'model-a'), job('job-b', 'model-b')]
    api.get.mockImplementation((url: string) => {
      if (url.endsWith('/chapters')) return Promise.resolve({ data: { data: { items: [], total: 0 } } })
      if (url.endsWith('/cataloging/jobs')) return Promise.resolve({ data: { data: { items: jobs, total: 2 } } })
      if (url.endsWith('/cataloging/job-a')) return first.promise
      if (url.endsWith('/cataloging/job-b')) return second.promise
      if (url.endsWith('/candidates') || url.endsWith('/facts')) {
        return Promise.resolve({ data: { data: { items: [], total: 0 } } })
      }
      return Promise.reject(new Error(`unexpected GET ${url}`))
    })

    render(<CatalogingPage projectId="project-1" />)
    const loadButtons = await screen.findAllByRole('button', { name: '载入任务' })
    fireEvent.click(loadButtons[0])
    fireEvent.click(loadButtons[1])

    await act(async () => {
      second.resolve({ data: { data: { job: jobs[1], runs: [run('run-b', 'job-b', 'B 章节')] } } })
      await second.promise
    })
    expect(await screen.findByText('model-b · task')).toBeInTheDocument()
    expect(screen.getByText('B 章节')).toBeInTheDocument()

    await act(async () => {
      first.resolve({ data: { data: { job: jobs[0], runs: [run('run-a', 'job-a', 'A 迟到章节')] } } })
      await first.promise
    })
    expect(screen.getByText('model-b · task')).toBeInTheDocument()
    expect(screen.queryByText('model-a · task')).not.toBeInTheDocument()
    expect(screen.queryByText('A 迟到章节')).not.toBeInTheDocument()
  })
})
