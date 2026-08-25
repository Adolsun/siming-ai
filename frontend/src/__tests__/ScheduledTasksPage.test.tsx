import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

const api = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
}))

vi.mock('../api/client', () => ({ apiClient: api }))

import { ScheduledTasksPage } from '../pages/ScheduledTasksPage'

const task = {
  id: 'task-1',
  project_id: 'project-1',
  name: '每日灵感搜集',
  prompt: '整理今天的灵感',
  cron_expr: '0 9 * * *',
  interval_minutes: null,
  tool_policy: [],
  status: 'active',
  last_run_at: null,
  last_run_status: null,
  last_run_output: null,
  next_run_at: null,
  created_at: null,
  updated_at: null,
}

describe('ScheduledTasksPage deletion', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.get.mockResolvedValue({ data: { code: 0, message: 'ok', data: { items: [task], total: 1 } } })
    api.delete.mockResolvedValue({ data: { code: 0, message: 'ok', data: null } })
  })

  it('shows a named delete action, asks for confirmation, and removes the row immediately', async () => {
    render(<ScheduledTasksPage projectId="project-1" />)

    expect(await screen.findByText('每日灵感搜集')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '删除任务每日灵感搜集' }))
    expect(await screen.findByText('删除任务“每日灵感搜集”？')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '确认删除' }))
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/projects/project-1/scheduled-tasks/task-1'))
    await waitFor(() => expect(screen.queryByText('每日灵感搜集')).not.toBeInTheDocument())
  })
})
