import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { createSimingQueryClient } from '../shared/query/client'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn() }))
vi.mock('../shared/api/client', () => ({ apiClient: api }))

import NarrativeGovernancePage from '../pages/NarrativeGovernancePage'
import { restoreNarrativeCheckpoint } from '../features/narrativeGovernance/api'

const emptyDashboard = {
  foreshadowings: [], causal_edges: [], narrative_debts: [], character_states: [], quality_metrics: [], checkpoints: [], chapter_reviews: [],
  coverage: { total_chapters: 0, assessed_chapters: 0, verified_chapters: 0, gaps: 0 },
  counts: { open_foreshadowings: 0, open_causal_edges: 0, open_debts: 0, pending_review: 0, stale: 0, coverage_gaps: 0 },
}

const chapterReview = {
  id: 'review-1',
  chapter_id: 'c1',
  chapter_title: '第一章 门后脚步',
  chapter_version: 2,
  status: 'assessed',
  source: 'llm',
  findings_count: 1,
  evidence: '已检查伏笔、因果与未完成行动',
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

  it('submits a repair for review instead of directly closing it', async () => {
    api.get.mockResolvedValue({ data: { data: {
      ...emptyDashboard,
      foreshadowings: [{ id: 'f1', title: '断剑血纹', status: 'open', importance: 'high', source_chapter_id: 'c1' }],
      chapter_reviews: [chapterReview],
      coverage: { total_chapters: 1, assessed_chapters: 1, verified_chapters: 0, gaps: 0 },
      counts: { ...emptyDashboard.counts, open_foreshadowings: 1 },
    } } })
    api.patch.mockResolvedValue({ data: { code: 0, data: { id: 'f1', status: 'pending_review' } } })
    renderPage()
    await screen.findByText('断剑血纹')
    expect(screen.getByText('待处理')).toBeInTheDocument()
    expect(screen.queryByText('open')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /提交修复/ }))
    fireEvent.change(await screen.findByLabelText('解决说明'), { target: { value: '第二版正文已经解释血纹来自旧祭坛' } })
    fireEvent.change(screen.getByLabelText('正文证据（建议填写）'), { target: { value: '第二章末尾铸剑师明确说明来源' } })
    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      '/projects/p1/narrative-governance/items/foreshadowings/f1',
      expect.objectContaining({
        status: 'pending_review',
        resolved_chapter_id: 'c1',
        resolution_note: '第二版正文已经解释血纹来自旧祭坛',
        resolution_evidence: '第二章末尾铸剑师明确说明来源',
        closed_by: 'user',
      }),
    ))
  })

  it('only closes a pending item after a written verification', async () => {
    api.get.mockResolvedValue({ data: { data: {
      ...emptyDashboard,
      foreshadowings: [{
        id: 'f1', title: '断剑血纹', status: 'pending_review', importance: 'high',
        source_chapter_id: 'c1', resolved_chapter_id: 'c1',
        resolution_note: '正文已交代血纹来源', evidence: '第一章发现无法解释的血纹',
        resolution_evidence: '第二章末尾的铸剑师证词',
      }],
      chapter_reviews: [chapterReview],
      coverage: { total_chapters: 1, assessed_chapters: 1, verified_chapters: 0, gaps: 0 },
      counts: { ...emptyDashboard.counts, open_foreshadowings: 1, pending_review: 1 },
    } } })
    api.patch.mockResolvedValue({ data: { code: 0, data: { id: 'f1', status: 'fulfilled' } } })
    renderPage()
    await screen.findByText('断剑血纹')
    fireEvent.click(screen.getByRole('button', { name: /复检关闭/ }))
    fireEvent.change(await screen.findByLabelText('复检结论'), { target: { value: '复读前后文后确认伏笔已经完整闭合' } })
    fireEvent.click(screen.getByRole('button', { name: /确\s*认\s*闭\s*环/ }))
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      '/projects/p1/narrative-governance/items/foreshadowings/f1',
      expect.objectContaining({
        status: 'fulfilled',
        resolved_chapter_id: 'c1',
        resolution_note: '正文已交代血纹来源',
        resolution_evidence: '第二章末尾的铸剑师证词',
        verification_note: '复读前后文后确认伏笔已经完整闭合',
      }),
    ))
  })

  it('requires an explicit restore confirmation payload', async () => {
    api.post.mockResolvedValue({ data: { code: 0, data: {} } })
    await restoreNarrativeCheckpoint('p1', 'checkpoint-1')
    expect(api.post).toHaveBeenCalledWith(
      '/projects/p1/narrative-governance/checkpoints/checkpoint-1/restore',
      { confirmation: 'restore' },
    )
  })
})
