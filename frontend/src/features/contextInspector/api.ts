import { apiClient } from '../../shared/api/client'
import type { ContextTrace, TraceEvent, TraceHealth, TraceScope } from './types'

interface Envelope<T> { data: T }
const root = '/context-traces'

export async function traceDetail(id: string, signal: AbortSignal) {
  return (await apiClient.get<Envelope<ContextTrace>>(`${root}/${id}`, undefined, { signal })).data.data
}

export async function listTraces(scope: TraceScope | undefined, correlationId: string | undefined, before: number | null, signal: AbortSignal) {
  return (await apiClient.post<Envelope<{ items: ContextTrace[]; next_cursor: number | null }>>(`${root}/search`, {
    scope, correlation_id: correlationId, before, limit: 30,
  }, { signal })).data.data
}

export async function traceEvents(id: string, after: number, signal: AbortSignal) {
  return (await apiClient.get<Envelope<{ items: TraceEvent[] }>>(`${root}/${id}/events`, { after, limit: 100 }, { signal })).data.data.items
}

export async function tracePayload(id: string, payloadId: string, offset: number, signal: AbortSignal) {
  return (await apiClient.get<Envelope<{ content: string; total_characters: number; next_offset: number }>>(`${root}/${id}/payloads/${payloadId}`, { offset }, { signal })).data.data
}

export async function traceHealth(signal: AbortSignal) {
  return (await apiClient.get<Envelope<TraceHealth>>(`${root}/settings`, undefined, { signal })).data.data
}

export async function setTraceMode(mode: TraceHealth['policy']['mode'], timed = false) {
  await apiClient.put(`${root}/settings`, { mode, duration_minutes: timed ? 60 : null })
}

export async function clearTraces() { await apiClient.delete(root) }

export async function exportTrace(id: string) {
  const response = await apiClient.get<Blob>(`${root}/${id}/export`, undefined, { responseType: 'blob' })
  const url = URL.createObjectURL(response.data)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `siming-trace-${id}.zip`
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
