import { useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type { OperationRun } from '../../shared/api/contracts'
import { operationKeys } from '../../shared/operations/queries'

export { listOperations, operationKeys, useOperations } from '../../shared/operations/queries'

export function useOperationAction(limit = 30) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async ({ operationId, action }: { operationId: string; action: string }) => {
      await apiClient.post(`/operations/${operationId}/${action}`)
    },
    onSuccess: () => client.invalidateQueries({ queryKey: operationKeys.list(limit) }),
  })
}

export function useDeleteOperations(limit = 30) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (operationIds: string[]) => {
      for (const operationId of operationIds) {
        await apiClient.delete(`/operations/${operationId}`)
      }
    },
    onSuccess: () => client.invalidateQueries({ queryKey: operationKeys.list(limit) }),
  })
}

export async function markOperationAttentionRead(operationIds: string[]) {
  await apiClient.post('/operations/attention/read', { operation_ids: operationIds })
}

export function updateOperationInCache(
  current: OperationRun[] | undefined,
  operation: OperationRun,
) {
  if (!current) return [operation]
  const found = current.some((item) => item.id === operation.id)
  return found
    ? current.map((item) => item.id === operation.id ? operation : item)
    : [operation, ...current]
}
