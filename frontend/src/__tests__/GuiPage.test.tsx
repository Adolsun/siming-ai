import { act, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import GuiPage from '../pages/GuiPage'

vi.mock('../pages/SettingsPage', () => ({ default: () => <div>设置页</div> }))
vi.mock('../pages/ExternalAgentPage', () => ({ default: () => <div>外部 Agent 页</div> }))
vi.mock('../components/GuiAssistantChat', () => ({ default: () => <div>AI 助手页</div> }))
vi.mock('../pages/TerminalPage', () => ({ default: () => <div>日志页</div> }))
vi.mock('../pages/ModelCenterPage', () => ({ default: () => <div>模型页</div> }))
vi.mock('../pages/GettingStartedPage', () => ({ GettingStartedPanel: () => <div>快速开始页</div> }))
vi.mock('../components/TabCache', () => ({ default: () => <div>当前页面</div> }))
vi.mock('../themes/ThemeSwitcher', () => ({ default: () => <button type="button">主题</button> }))

const COMPACT_QUERY = '(max-width: 760px)'

describe('GuiPage responsive navigation', () => {
  let compact = false
  let listeners: Set<(event: MediaQueryListEvent) => void>

  beforeEach(() => {
    compact = false
    listeners = new Set()
    vi.stubGlobal('matchMedia', vi.fn((query: string) => ({
      matches: query === COMPACT_QUERY ? compact : false,
      media: query,
      onchange: null,
      addListener: (listener: (event: MediaQueryListEvent) => void) => {
        if (query === COMPACT_QUERY) listeners.add(listener)
      },
      removeListener: (listener: (event: MediaQueryListEvent) => void) => listeners.delete(listener),
      addEventListener: (_event: string, listener: (event: MediaQueryListEvent) => void) => {
        if (query === COMPACT_QUERY) listeners.add(listener)
      },
      removeEventListener: (_event: string, listener: (event: MediaQueryListEvent) => void) => listeners.delete(listener),
      dispatchEvent: () => false,
    })))
  })

  it('keeps React navigation state aligned with the forced compact rail', () => {
    compact = true
    const { container } = render(<MemoryRouter><GuiPage /></MemoryRouter>)

    expect(container.querySelector('.ant-layout-sider-collapsed')).toBeInTheDocument()
    expect(screen.queryByText('创作控制台')).not.toBeInTheDocument()
    expect(screen.queryByText('创作入口')).not.toBeInTheDocument()
    expect(screen.queryByText('连接与能力')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '展开导航' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '收起导航' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '进入作品库' })).toBeInTheDocument()
  })

  it('restores the full navigation when the viewport leaves compact mode', () => {
    compact = true
    const { container } = render(<MemoryRouter><GuiPage /></MemoryRouter>)

    compact = false
    act(() => {
      for (const listener of listeners) listener({ matches: false } as MediaQueryListEvent)
    })

    expect(container.querySelector('.ant-layout-sider-collapsed')).not.toBeInTheDocument()
    expect(screen.getByText('创作控制台')).toBeInTheDocument()
    expect(screen.getByText('创作入口')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '收起导航' })).toBeInTheDocument()
  })
})
