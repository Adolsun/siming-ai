import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { createSimingQueryClient } from '../shared/query/client'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn() }))
vi.mock('../shared/api/client', () => ({ apiClient: api }))

import NarrativeGovernancePage from '../pages/NarrativeGovernancePage'

const emptyDashboard = {
  foreshadowings: [], causal_edges: [], narrative_debts: [], character_states: [], quality_metrics: [], checkpoints: [],
  counts: { open_foreshadowings: 0, open_causal_edges: 0, open_debts: 0 },
}

const renderPage = () => render(
  <QueryClientProvider client={createSimingQueryClient()}>
    <MemoryRouter><NarrativeGovernancePage projectId="p1" /></MemoryRouter>
  </QueryClientProvider>,
)

describe('NarrativeGovernancePage', () => {
  beforeEach(() => {
    api.get.mockReset()
    api.post.mockReset()
    api.patch.mockReset()
  })

  it('renders the empty governance state', async () => {
    api.get.mockResolvedValue({ data: { data: emptyDashboard } })
    renderPage()
    expect(await screen.findByText('还没有可治理的叙事记录')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '前往作品建档' })).toBeInTheDocument()
  })

  it('switches to the high-risk filter', async () => {
    api.get.mockResolvedValue({ data: { data: emptyDashboard } })
    renderPage()
    await screen.findByText('还没有可治理的叙事记录')
    fireEvent.click(screen.getByText('高风险'))
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith('/projects/p1/narrative-governance', { view: 'risk' }))
  })

  it('marks a foreshadowing fulfilled', async () => {
    api.get.mockResolvedValue({ data: { data: { ...emptyDashboard, foreshadowings: [{ id: 'f1', title: '断剑血纹', status: 'open', importance: 'high' }], counts: { ...emptyDashboard.counts, open_foreshadowings: 1 } } } })
    api.patch.mockResolvedValue({ data: { code: 0 } })
    renderPage()
    await screen.findByText('断剑血纹')
    expect(screen.getByText('进行中')).toBeInTheDocument()
    expect(screen.queryByText('open')).not.toBeInTheDocument()
    fireEvent.click(screen.getByTitle('标记兑现'))
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/projects/p1/narrative-governance/items/foreshadowings/f1', { status: 'fulfilled' }))
  })
})
