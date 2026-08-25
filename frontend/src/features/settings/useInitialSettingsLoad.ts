import { useEffect } from 'react'

export function useInitialSettingsLoad(
  fetchContentRoot: () => Promise<void>,
  fetchLauncherSettings: () => Promise<void>,
) {
  useEffect(() => {
    void fetchContentRoot()
    void fetchLauncherSettings()
  }, [fetchContentRoot, fetchLauncherSettings])
}
