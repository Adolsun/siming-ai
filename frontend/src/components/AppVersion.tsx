import { useEffect, useState } from 'react'
import { apiClient } from '../api/client'

interface AppInfoResponse {
  data: {
    name: string
    version: string
  }
}

let cachedVersion = ''

export default function AppVersion({ className = '' }: { className?: string }) {
  const [version, setVersion] = useState(cachedVersion)

  useEffect(() => {
    if (cachedVersion) return
    let active = true
    void (async () => {
      try {
        const response = await apiClient.get<AppInfoResponse>('/config/app-info')
        const next = String(response?.data?.data?.version || '').trim()
        if (!next) return
        cachedVersion = next
        if (active) setVersion(next)
      } catch {
        // Version display is informational and must never block navigation.
      }
    })()
    return () => { active = false }
  }, [])

  if (!version) return null
  return <span className={className} aria-label={`司命版本 ${version}`}>v{version}</span>
}
