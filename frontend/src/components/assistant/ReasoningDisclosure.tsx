import { useEffect, useId, useState } from 'react'
import { BulbOutlined, DownOutlined, LoadingOutlined } from '@ant-design/icons'
import './ReasoningDisclosure.css'

function StreamingReasoningText({ content, streaming }: { content: string; streaming: boolean }) {
  return (
    <div className="assistant-reasoning-text">
      {content}
      {streaming && <span className="assistant-reasoning-caret" aria-hidden="true" />}
    </div>
  )
}

export interface ReasoningDisclosureProps {
  content?: string | null
  streaming?: boolean
}

/** Displays only reasoning text explicitly returned by the configured model API. */
export function ReasoningDisclosure({
  content,
  streaming = false,
}: ReasoningDisclosureProps) {
  const normalizedContent = String(content || '').trim()
  const [expanded, setExpanded] = useState(streaming)
  const contentId = useId()
  useEffect(() => {
    if (streaming) setExpanded(true)
  }, [streaming])

  if (!normalizedContent) return null

  return (
    <section className={`assistant-reasoning${streaming ? ' assistant-reasoning-streaming' : ''}`}>
      <button
        type="button"
        className="assistant-reasoning-trigger"
        aria-controls={contentId}
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        <span className="assistant-reasoning-title">
          <BulbOutlined aria-hidden="true" />
          模型思考摘要
        </span>
        <span className="assistant-reasoning-state">
          {streaming ? (
            <>
              <LoadingOutlined spin aria-hidden="true" />
              实时生成
            </>
          ) : '已完成'}
          <DownOutlined className="assistant-reasoning-chevron" aria-hidden="true" />
        </span>
      </button>
      <div
        className={`assistant-reasoning-region${expanded ? ' assistant-reasoning-region-open' : ''}`}
        aria-hidden={!expanded}
      >
        <div className="assistant-reasoning-region-inner">
          <div id={contentId} className="assistant-reasoning-body">
            <div className="assistant-reasoning-note">仅展示模型 API 实际返回的可见推理内容</div>
            <StreamingReasoningText content={normalizedContent} streaming={streaming} />
          </div>
        </div>
      </div>
    </section>
  )
}
