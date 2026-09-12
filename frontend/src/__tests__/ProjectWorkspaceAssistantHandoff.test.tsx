import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom'

vi.mock('../features/projects', () => ({
  useProject: () => ({
    data: { id: 'project-1', title: '灰港遗忘症' },
    isError: false,
    error: null,
    refetch: vi.fn(),
  }),
}))
vi.mock('../shared/operations/queries', () => ({ useOperations: () => ({ data: [] }) }))

vi.mock('../components/AiSidePanel', () => ({
  default: ({ collapsed, children }: { collapsed: boolean; children: React.ReactNode }) => (
    <aside data-testid="project-assistant-panel" data-collapsed={String(collapsed)}>{children}</aside>
  ),
}))

vi.mock('../pages/WriterPage', () => ({ default: () => <input aria-label="未保存正文" defaultValue="原始草稿" /> }))
vi.mock('../pages/CatalogingPage', () => ({ default: ({ focusJobId, active }: { focusJobId?: string; active: boolean }) => <output data-testid="cataloging-target">{focusJobId}:{String(active)}</output> }))
vi.mock('../components/WorkspaceAssistantChat', () => ({ default: () => <div>项目助手内容</div> }))
vi.mock('../themes/ThemeSwitcher', () => ({ default: () => null }))
vi.mock('../contexts/AiPanelContext', () => ({
  AiPanelProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useAiPanelContext: () => ({
    selectedText: undefined,
    selectedTextChapterId: undefined,
    triggerRefresh: vi.fn(),
  }),
}))
vi.mock('../hooks/useModelOptions', () => ({
  useModelOptions: () => ({ modelOptions: [], defaultModel: undefined, loading: false, setGlobalModel: vi.fn() }),
}))
vi.mock('../hooks/usePanelResize', () => ({
  usePanelResize: () => ({ width: 360, onDragHandleMouseDown: vi.fn(), dragging: false }),
}))

import ProjectWorkspace from '../pages/ProjectWorkspace'

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{location.pathname}{location.search}</output>
}

function TaskLinks() {
  const navigate = useNavigate()
  return <><button onClick={() => navigate('/project/project-1?view=cataloging&job=job-a')}>打开任务A</button>
    <button onClick={() => navigate('/project/project-1?view=cataloging&job=job-b')}>打开任务B</button>
    <button onClick={() => navigate('/project/project-1?view=writer')}>返回正文</button></>
}

describe('ProjectWorkspace formal-project handoff', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('siming_ai_panel_collapsed', 'true')
  })

  it('forwards a new linked job through cached tabs while preserving the writer draft', async () => {
    render(<MemoryRouter initialEntries={['/project/project-1?view=writer']}><TaskLinks /><Routes>
      <Route path="/project/:projectId" element={<ProjectWorkspace />} />
    </Routes></MemoryRouter>)
    fireEvent.change(await screen.findByRole('textbox', { name: '未保存正文' }), { target: { value: '作者修改尚未保存' } })
    fireEvent.click(screen.getByRole('button', { name: '打开任务A' }))
    expect(await screen.findByTestId('cataloging-target')).toHaveTextContent('job-a:true')
    fireEvent.click(screen.getByRole('button', { name: '返回正文' }))
    expect(screen.getByTestId('cataloging-target')).toHaveTextContent(':false')
    expect(screen.getByRole('textbox', { name: '未保存正文' })).toHaveValue('作者修改尚未保存')
    fireEvent.click(screen.getByRole('button', { name: '打开任务B' }))
    expect(screen.getByTestId('cataloging-target')).toHaveTextContent('job-b:true')
  })

  it('opens the project assistant and consumes the one-shot handoff query', async () => {
    render(
      <MemoryRouter initialEntries={['/project/project-1?assistant=open']}>
        <Routes>
          <Route
            path="/project/:projectId"
            element={<><ProjectWorkspace /><LocationProbe /></>}
          />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByRole('button', { name: '收起项目助手' })).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByTestId('project-assistant-panel')).toHaveAttribute('data-collapsed', 'false')
    expect(screen.getByText('项目助手内容')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/project/project-1'))
    expect(screen.getByTestId('location')).not.toHaveTextContent('assistant=open')
    expect(localStorage.getItem('siming_ai_panel_collapsed')).toBe('false')
  })
})
