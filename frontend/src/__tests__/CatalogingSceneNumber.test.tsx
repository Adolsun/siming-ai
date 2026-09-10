import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import CatalogingCandidatePayloadEditor from '../pages/CatalogingCandidatePayloadEditor'
import type { CatalogingCandidate } from '../pages/catalogingTypes'

describe('cataloging scene number editing', () => {
  const candidate: CatalogingCandidate = {
    id: 'candidate', chapter_id: 'chapter', chapter_run_id: 'run',
    item_type: 'outline_create', status: 'pending',
    payload: { node_type: 'section', scene_number: 4, summary: '审批通过后签字。' },
  }

  it('lets the author set an explicit number while preserving the scene text', () => {
    const change = vi.fn()
    render(<CatalogingCandidatePayloadEditor candidate={candidate}
      draft={JSON.stringify(candidate.payload)} onDraftChange={change} />)
    fireEvent.change(screen.getByRole('spinbutton', { name: '场景编号' }), { target: { value: '3' } })
    expect(change).toHaveBeenCalled()
    const [id, draft] = change.mock.calls[change.mock.calls.length - 1]
    expect(id).toBe(candidate.id)
    expect(JSON.parse(draft)).toEqual({ ...candidate.payload, scene_number: 3 })
  })

  it('disables number editing together with the other candidate fields', () => {
    render(<CatalogingCandidatePayloadEditor candidate={candidate}
      draft={JSON.stringify(candidate.payload)} onDraftChange={vi.fn()} disabled />)
    expect(screen.getByRole('spinbutton', { name: '场景编号' })).toBeDisabled()
  })
})
