import { apiClient } from '../../api/client'
import type {
  GatewayAdminSession,
  GatewayAdminSessionStatus,
  GatewayDevice,
  GatewayRuntimeCapabilities,
  GatewayStatus,
  PairingStart,
  PairingStatus,
  SyncConflict,
  SyncProject,
} from './types'

interface Envelope<T> {
  code: number
  message: string
  data: T
}

export async function getGatewayCapabilities() {
  const response = await apiClient.get<Envelope<GatewayRuntimeCapabilities>>('/runtime/capabilities')
  return response.data.data
}

export async function getGatewayStatus() {
  const response = await apiClient.get<Envelope<GatewayStatus>>('/sync/status')
  return response.data.data
}

export async function loginGatewayAdmin(bootstrapKey: string) {
  const response = await apiClient.post<Envelope<GatewayAdminSession>>('/auth/admin/login', {
    bootstrap_key: bootstrapKey,
  })
  return response.data.data
}

export async function getGatewayAdminSession() {
  const response = await apiClient.get<Envelope<GatewayAdminSessionStatus>>('/auth/admin/session')
  return response.data.data
}

export async function listSyncProjects() {
  const response = await apiClient.get<Envelope<SyncProject[]>>('/sync/projects')
  return response.data.data
}

export async function enableProjectSync(projectId: string) {
  const response = await apiClient.post<Envelope<SyncProject>>(`/sync/projects/${projectId}/enable`)
  return response.data.data
}

export async function disableProjectSync(projectId: string) {
  await apiClient.delete(`/sync/projects/${projectId}`)
}

export async function listGatewayDevices() {
  const response = await apiClient.get<Envelope<GatewayDevice[]>>('/devices')
  return response.data.data
}

export async function revokeGatewayDevice(deviceId: string) {
  await apiClient.delete(`/devices/${deviceId}`)
}

export async function startGatewayPairing() {
  const response = await apiClient.post<Envelope<PairingStart>>('/pairing/start')
  return response.data.data
}

export async function getGatewayPairingStatus(pairingId: string) {
  const response = await apiClient.get<Envelope<PairingStatus>>(`/pairing/${pairingId}`)
  return response.data.data
}

export async function approveGatewayPairing(pairingId: string) {
  await apiClient.post('/pairing/approve', { pairing_id: pairingId })
}

export async function listSyncConflicts() {
  const response = await apiClient.get<Envelope<SyncConflict[]>>('/sync/conflicts', { status: 'open' })
  return response.data.data
}

export async function resolveSyncConflict(conflictId: string, choice: 'server' | 'client') {
  const response = await apiClient.post<Envelope<SyncConflict>>(
    `/sync/conflicts/${conflictId}/resolve`,
    { choice },
  )
  return response.data.data
}
