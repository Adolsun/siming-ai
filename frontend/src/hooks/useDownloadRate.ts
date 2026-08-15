import { useEffect, useRef, useState } from 'react'

interface DownloadRateSample {
  active: boolean
  bytes?: number
  source?: string | null
}

interface TimedDownloadSample {
  bytes: number
  at: number
  source?: string | null
}

export function useDownloadRate(sample: DownloadRateSample) {
  const [bytesPerSecond, setBytesPerSecond] = useState<number | null>(null)
  const previousRef = useRef<TimedDownloadSample | null>(null)

  useEffect(() => {
    if (!sample.active) {
      previousRef.current = null
      setBytesPerSecond(null)
      return
    }

    const current = {
      bytes: sample.bytes || 0,
      at: Date.now(),
      source: sample.source,
    }
    const previous = previousRef.current
    previousRef.current = current
    if (!previous || previous.source !== current.source || current.bytes < previous.bytes) {
      setBytesPerSecond(null)
      return
    }

    const elapsedSeconds = (current.at - previous.at) / 1000
    const transferred = current.bytes - previous.bytes
    if (elapsedSeconds > 0 && transferred > 0) {
      setBytesPerSecond(transferred / elapsedSeconds)
    }
  }, [sample.active, sample.bytes, sample.source])

  return bytesPerSecond
}
