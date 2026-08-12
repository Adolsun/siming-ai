import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  getNarrativeDashboard,
  restoreNarrativeCheckpoint,
  updateNarrativeStatus,
  verifyNarrativeReview,
  type GovernanceStatusPayload,
} from './api'

export const narrativeKeys = {
  all: (projectId: string) => ['narrative-governance', projectId] as const,
  dashboard: (projectId: string, view: string) => (
    [...narrativeKeys.all(projectId), view] as const
  ),
}

export function useNarrativeDashboard(projectId: string, view: string) {
  return useQuery({
    queryKey: narrativeKeys.dashboard(projectId, view),
    queryFn: () => getNarrativeDashboard(projectId, view),
    // Cataloging may be committed by a background local CLI process rather
    // than by a mutation in this React tree. Always refresh when the page is
    // entered and poll while it is visible so applied governance data cannot
    // remain hidden behind a stale query cache.
    refetchOnMount: 'always',
    refetchInterval: 3_000,
  })
}

export function useUpdateNarrativeStatus(projectId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: { type: string; id: string; payload: GovernanceStatusPayload }) => (
      updateNarrativeStatus(projectId, input.type, input.id, input.payload)
    ),
    onSuccess: () => client.invalidateQueries({ queryKey: narrativeKeys.all(projectId) }),
  })
}

export function useVerifyNarrativeReview(projectId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: { reviewId: string; evidence: string }) => (
      verifyNarrativeReview(projectId, input.reviewId, input.evidence)
    ),
    onSuccess: () => client.invalidateQueries({ queryKey: narrativeKeys.all(projectId) }),
  })
}

export function useRestoreNarrativeCheckpoint(projectId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (checkpointId: string) => restoreNarrativeCheckpoint(projectId, checkpointId),
    onSuccess: () => client.invalidateQueries({ queryKey: narrativeKeys.all(projectId) }),
  })
}
