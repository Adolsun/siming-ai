import { render } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import type { OperationRun } from '../shared/api/contracts'

const runtime = vi.hoisted(() => ({ data: undefined as OperationRun[] | undefined, refresh: vi.fn() }))
vi.mock('../shared/operations/queries', () => ({ useOperations: () => ({ data: runtime.data }) }))
vi.mock('../contexts/AiPanelContext', () => ({ useAiPanelContext: () => ({ triggerRefresh: runtime.refresh }) }))
import { CatalogingRefreshBridge } from '../features/cataloging/CatalogingRefreshBridge'

beforeEach(() => { runtime.data = undefined; runtime.refresh.mockClear() })

it('refreshes cached tabs on cataloging completion without mounting the assistant', () => {
  const view = render(<CatalogingRefreshBridge projectId="p" />)
  const job = { id: 'job', source_kind: 'cataloging', project_id: 'p', status: 'running', progress: { current: 0 } } as OperationRun
  runtime.data = [job]
  view.rerender(<CatalogingRefreshBridge projectId="p" />)
  expect(runtime.refresh).not.toHaveBeenCalled()
  runtime.data = [{ ...job, status: 'completed', completed_at: '2026-09-12T08:43:16Z', progress: { mode: 'determinate', current: 1 } }]
  view.rerender(<CatalogingRefreshBridge projectId="p" />)
  expect(runtime.refresh).toHaveBeenCalledTimes(1)
  runtime.data = (runtime.data || []).map((row) => ({ ...row, attention_read_at: '2026-09-12T08:44:00Z' }))
  view.rerender(<CatalogingRefreshBridge projectId="p" />)
  expect(runtime.refresh).toHaveBeenCalledTimes(1)
})

it('covers completion before the first poll and ignores other projects', () => {
  runtime.data = [{ id: 'job', source_kind: 'cataloging', project_id: 'p', status: 'completed' } as OperationRun]
  const view = render(<CatalogingRefreshBridge projectId="p" />)
  expect(runtime.refresh).toHaveBeenCalledTimes(1)
  view.rerender(<CatalogingRefreshBridge projectId="another-project" />)
  expect(runtime.refresh).toHaveBeenCalledTimes(1)
})
