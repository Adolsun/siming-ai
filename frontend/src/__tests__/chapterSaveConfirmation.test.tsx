import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { isCancel, type AxiosAdapter } from 'axios'
import { Modal } from 'antd'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from '../api/client'

vi.unmock('axios')

describe('chapter save confirmation at the API boundary', () => {
  const confirm = Modal.confirm
  beforeEach(() => {
    // jsdom does not dispatch CSS transition-end events for Ant Design portals.
    vi.spyOn(Modal, 'confirm').mockImplementation((config) => confirm({
      ...config, transitionName: '', maskTransitionName: '',
    }))
  })
  afterEach(async () => {
    act(() => Modal.destroyAll())
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    vi.restoreAllMocks()
  })

  const adapter = () => vi.fn<AxiosAdapter>(async (config) => ({
    data: { data: { id: 'chapter-1' } }, status: 200, statusText: 'OK', headers: {}, config,
  }))

  it('returning to the editor cancels the write instead of choosing semantic impact', async () => {
    const transport = adapter()
    const outcome = apiClient.put('/projects/project-1/chapters/chapter-1', {
      content: '当前修改', cataloging_mode: 'save_only',
    }, { adapter: transport }).catch((error: unknown) => error)
    fireEvent.click(await screen.findByRole('button', { name: '返回编辑' }))
    expect(isCancel(await outcome)).toBe(true)
    expect(transport).not.toHaveBeenCalled()
  })

  it.each([
    ['仅润色并保存', 'style_only'],
    ['剧情有变化并保存', 'semantic'],
  ])('sends the explicitly selected %s impact to the same save API', async (label, impact) => {
    const transport = adapter()
    const saving = apiClient.put('/projects/project-1/chapters/chapter-1', {
      content: '当前修改', cataloging_mode: 'save_only',
    }, { adapter: transport })
    fireEvent.click(await screen.findByRole('button', { name: label }))
    await saving
    expect(transport).toHaveBeenCalledTimes(1)
    expect(transport.mock.calls[0][0].headers.get('X-Siming-Cataloging-Impact')).toBe(impact)
  })

  it('does not ask again when the caller already supplied a structured impact', async () => {
    const transport = adapter()
    await apiClient.put('/projects/project-1/chapters/chapter-1', {
      content: '当前修改', cataloging_mode: 'save_only',
    }, { adapter: transport, headers: { 'X-Siming-Cataloging-Impact': 'style_only' } })
    expect(transport).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
