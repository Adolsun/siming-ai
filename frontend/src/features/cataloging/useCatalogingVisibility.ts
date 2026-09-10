import { useEffect } from 'react'
import type { MutableRefObject } from 'react'
import type { LatestRequestGate } from '../../shared/latestRequest'

interface CatalogingVisibilityOptions {
  active: boolean
  focusJobId?: string
  lastOpenedJobIdRef: MutableRefObject<string | null>
  activeJobIdRef: MutableRefObject<string | null>
  jobLoadAbortRef: MutableRefObject<AbortController | null>
  loadJobRequestGate: MutableRefObject<LatestRequestGate<string>>
  loadJob: (jobId: string) => Promise<void>
  stopProgressStream: () => void
  setStreaming: (streaming: boolean) => void
  setJobLoading: (loading: boolean) => void
}

/** Own the observer lifetime without changing the cataloging worker state. */
export function useCatalogingVisibility({
  active, focusJobId, lastOpenedJobIdRef, activeJobIdRef, jobLoadAbortRef,
  loadJobRequestGate, loadJob, stopProgressStream, setStreaming, setJobLoading,
}: CatalogingVisibilityOptions) {
  useEffect(() => {
    if (active) {
      const target = focusJobId || lastOpenedJobIdRef.current
      if (target) void loadJob(target)
    }
    return () => {
      loadJobRequestGate.current.invalidate()
      jobLoadAbortRef.current?.abort()
      activeJobIdRef.current = null
      stopProgressStream()
      setStreaming(false)
      setJobLoading(false)
    }
  }, [active, focusJobId, loadJob, stopProgressStream, lastOpenedJobIdRef,
    loadJobRequestGate, jobLoadAbortRef, activeJobIdRef, setStreaming, setJobLoading])
}
