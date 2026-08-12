import { Typography } from 'antd'

const { Text } = Typography

interface ModelReadinessBannerProps {
  ready: boolean
  detail: string
}

export default function ModelReadinessBanner({ ready, detail }: ModelReadinessBannerProps) {
  return (
    <section
      className={`settings-readiness-banner${ready ? ' settings-readiness-ready' : ''}`}
      aria-label="AI 可用状态"
      role="status"
      aria-live="polite"
    >
      <span className="settings-readiness-dot" aria-hidden="true" />
      <div>
        <Text strong>{ready ? 'AI 已准备好' : '还没有可用于创作的模型'}</Text>
        <Text type="secondary">{detail}</Text>
      </div>
    </section>
  )
}
