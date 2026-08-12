import { useQuery } from '@tanstack/react-query'

import { apiClient } from '../api/client'
import type { ApiEnvelope, OperationListData } from '../api/contracts'

export const operationKeys = {
  all: ['operations'] as const,
  list: (limit = 30) => [...operationKeys.all, 'list', limit] as const,
  detail: (operationId: string) => [...operationKeys.all, 'detail', operationId] as const,
}

export async function listOperations(limit = 30) {
  const response = await apiClient.get<ApiEnvelope<OperationListData>>('/operations', { limit })
  return response.data.data.items
}

export function useOperations(limit = 30) {
  return useQuery({
    queryKey: operationKeys.list(limit),
    queryFn: () => listOperations(limit),
    refetchInterval: 3_000,
    staleTime: 1_000,
  })
}
