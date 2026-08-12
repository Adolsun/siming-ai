import { useEffect, useRef } from 'react'

interface CreationBriefLifecycleOptions {
  loadBrief: (quiet?: boolean) => Promise<void>
  dirty: boolean
  refreshKey: number
  onRemoteChangePending: (pending: boolean) => void
}

export function useCreationBriefLifecycle({
  loadBrief,
  dirty,
  refreshKey,
  onRemoteChangePending,
}: CreationBriefLifecycleOptions) {
  const lastRefreshKeyRef = useRef(refreshKey)

  useEffect(() => {
    void loadBrief()
  }, [loadBrief])

  useEffect(() => {
    if (lastRefreshKeyRef.current === refreshKey) return
    lastRefreshKeyRef.current = refreshKey
    if (dirty) {
      onRemoteChangePending(true)
      return
    }
    void loadBrief(true)
  }, [dirty, loadBrief, onRemoteChangePending, refreshKey])

  useEffect(() => {
    const guard = (event: BeforeUnloadEvent) => {
      if (!dirty) return
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', guard)
    return () => window.removeEventListener('beforeunload', guard)
  }, [dirty])
}
