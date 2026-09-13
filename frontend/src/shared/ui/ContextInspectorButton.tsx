import { Button } from 'antd'
import { BranchesOutlined } from '@ant-design/icons'
import { openContextInspector } from '../contextInspector'
import type { ContextInspectorRequest } from '../contextInspector'

export function ContextInspectorButton({ scope, correlationId, label = '查看本轮调用' }: ContextInspectorRequest & { label?: string }) {
  return <Button size="small" type="text" icon={<BranchesOutlined />} onClick={() => openContextInspector({ scope, correlationId })}>{label}</Button>
}
