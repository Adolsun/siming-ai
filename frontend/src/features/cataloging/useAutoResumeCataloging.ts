import { useEffect, useRef } from 'react'

interface ResumeCandidate {
  id: string
  execution_mode: string
  status: string
}

interface AutoResumeCatalogingOptions {
  job: ResumeCandidate | null
  streaming: boolean
  onLog: (message: string) => void
  onResume: (jobId: string) => void
}

/** Resume automatic jobs that were saved by an older build at a review checkpoint. */
export function useAutoResumeCataloging({
  job,
  streaming,
  onLog,
  onResume,
}: AutoResumeCatalogingOptions) {
  const attempted = useRef<Set<string>>(new Set())

  useEffect(() => {
    if (
      !job
      || job.execution_mode !== 'auto'
      || job.status !== 'waiting_confirmation'
      || streaming
      || attempted.current.has(job.id)
    ) return

    attempted.current.add(job.id)
    onLog('检测到旧版遗留的自动建档检查点，正在自动继续写入')
    onResume(job.id)
  }, [job, onLog, onResume, streaming])
}
