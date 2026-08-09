import { useEffect } from 'react'
import { Button, Typography } from 'antd'
import { MenuFoldOutlined, RobotOutlined } from '@ant-design/icons'
import './AiSidePanel.css'

const { Title } = Typography

interface AiSidePanelProps {
  collapsed: boolean
  onToggle: () => void
  width: number
  onResizeHandle: (e: React.MouseEvent) => void
  dragging: boolean
  children: React.ReactNode
}

function AiSidePanel({ collapsed, onToggle, width, onResizeHandle, dragging, children }: AiSidePanelProps) {
  useEffect(() => {
    if (collapsed) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onToggle()
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [collapsed, onToggle])

  if (collapsed) {
    return (
      <aside
        className="ai-side-panel ai-side-panel-collapsed"
        style={{ width: 0 }}
        aria-hidden="true"
      />
    )
  }

  return (
    <>
      <div className="ai-side-scrim" aria-hidden="true" onClick={onToggle} />
      <aside
        className={`ai-side-panel${dragging ? ' ai-side-panel-dragging' : ''}`}
        style={{ width }}
        aria-label="项目助手"
      >
        <div className="ai-side-panel-inner" style={{ width }}>
          <div className="ai-side-resize-handle" onMouseDown={onResizeHandle} />
          <div className="ai-side-head">
            <Title level={5} style={{ margin: 0 }}>
              <RobotOutlined /> 项目助手
            </Title>
            <Button type="text" size="small" icon={<MenuFoldOutlined />} aria-label="关闭项目助手面板" onClick={onToggle} />
          </div>
          <div className="ai-side-body">
            {children}
          </div>
        </div>
      </aside>
    </>
  )
}

export default AiSidePanel
