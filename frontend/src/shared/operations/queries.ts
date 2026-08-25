import { useQuery } from '@tanstack/react-query'

import { apiClient } from '../api/client'
import type { ApiEnvelope, OperationListData } from '../api/contracts'

export const operationKeys = {
  all: ['operations'] as const,
  list: (limit = 30, projectId = '', sourceKind = '') => (
    [...operationKeys.all, 'list', limit, projectId, sourceKind] as const
  ),
  detail: (operationId: string) => [...operationKeys.all, 'detail', operationId] as const,
}

export interface OperationListFilters {
  projectId?: string
  sourceKind?: string
}

export async function listOperations(limit = 30, filters: OperationListFilters = {}) {
  const response = await apiClient.get<ApiEnvelope<OperationListData>>('/operations', {
    limit,
    project_id: filters.projectId || undefined,
    source_kind: filters.sourceKind || undefined,
  })
  return response.data.data.items
}

export function useOperations(limit = 30, filters: OperationListFilters = {}) {
  return useQuery({
    queryKey: operationKeys.list(limit, filters.projectId, filters.sourceKind),
    queryFn: () => listOperations(limit, filters),
    refetchInterval: 3_000,
    staleTime: 1_000,
  })
}
