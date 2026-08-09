import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

const api = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}))

vi.mock('../api/client', () => ({ apiClient: api }))

import TerminalPage from '../pages/TerminalPage'

describe('TerminalPage log controls', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.get.mockResolvedValue({
      data: {
        code: 0,
        message: 'ok',
        data: {
          path: 'C:/Siming/logs/launcher.log',
          content: 'latest line\n',
          lines: 1,
          total: 20,
        },
      },
    })
  })

  it('clears only the view, pauses refresh, and reloads immediately when refresh resumes', async () => {
    render(<TerminalPage />)

    expect(await screen.findByText(/latest line/)).toBeInTheDocument()
    expect(screen.getByText(/最近 1\/20 行/)).toBeInTheDocument()
    const autoRefresh = screen.getByRole('switch', { name: '自动刷新日志' })
    expect(autoRefresh).toBeChecked()

    fireEvent.click(screen.getByRole('button', { name: '清空当前日志视图' }))
    expect(autoRefresh).not.toBeChecked()
    expect(screen.getByText('暂无日志输出')).toBeInTheDocument()

    fireEvent.click(autoRefresh)
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2))
    expect(await screen.findByText(/latest line/)).toBeInTheDocument()
  })
})
