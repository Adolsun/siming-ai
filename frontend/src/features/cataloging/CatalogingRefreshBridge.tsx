import { useEffect, useRef } from 'react'
import { useAiPanelContext } from '../../contexts/AiPanelContext'
import { useOperations } from '../../shared/operations/queries'

const terminalStatuses = new Set(['completed', 'failed', 'cancelled', 'interrupted'])

/** Refresh cached project tabs after durable cataloging writes, even with chat closed. */
export function CatalogingRefreshBridge({ projectId }: { projectId: string }) {
  const { triggerRefresh } = useAiPanelContext()
  const { data } = useOperations(100, { projectId, sourceKind: 'cataloging' })
  const previous = useRef<{ projectId: string; revision: string } | null>(null)
  const revision = data === undefined ? undefined : JSON.stringify(data
    .filter((item) => item.project_id === projectId && item.source_kind === 'cataloging')
    .filter((item) => terminalStatuses.has(item.status) || (item.progress?.current || 0) > 0)
    .map((item) => [item.id, item.status, item.progress?.current || 0, item.completed_at || ''])
    .sort((left, right) => String(left[0]).localeCompare(String(right[0]))))

  useEffect(() => {
    if (revision === undefined) return
    const last = previous.current
    previous.current = { projectId, revision }
    if (last?.projectId === projectId && last.revision === revision) return
    if (revision !== '[]' || last?.projectId === projectId) triggerRefresh()
  }, [projectId, revision, triggerRefresh])

  return null
}
