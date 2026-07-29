export interface LauncherGatewaySettings {
  gateway_enabled: boolean
  gateway_runtime_active: boolean
  gateway_headless?: boolean
  gateway_advertised_url: string
  gateway_allowed_hosts: string
}

export interface GatewayRuntimeCapabilities {
  runtime_profile: 'desktop-standalone' | 'gateway'
  sync_protocol_version: number
  gateway_authoritative: boolean
  pairing_enabled: boolean
  offline_replica_supported: boolean
  local_ai: boolean
  cli_worker: boolean
  mcp: boolean
  training: boolean
}

export interface GatewayStatus {
  protocol_version: number
  cursor: number
  enabled_projects: number
  open_conflicts: number
  active_devices: number
  tombstone_retention_days: number
}

export interface GatewayAdminSession {
  device_role: 'owner'
  expires_at: string
}

export interface GatewayAdminSessionStatus {
  authenticated: boolean
}

export interface SyncProject {
  project_id: string
  title: string
  status: 'not_enabled' | 'migrating' | 'enabled' | 'disabled' | 'error'
  entity_count: number
  counts: Record<string, number>
  aggregate_hash?: string | null
  initial_revision: number
  enabled_at?: string | null
  verified_at?: string | null
  last_error?: string | null
}

export interface GatewayDevice {
  id: string
  name: string
  platform: string
  role: string
  status: string
  protocol_version: number
  created_at: string
  approved_at?: string | null
  last_seen_at?: string | null
}

export interface PairingStart {
  pairing_id: string
  gateway_url: string
  gateway_name: string
  gateway_fingerprint: string
  expires_at: string
  qr_payload: Record<string, unknown>
}

export interface PairingStatus {
  pairing_id: string
  status: 'created' | 'pending_approval' | 'approved' | 'consumed' | 'expired'
  expires_at: string
  device_id?: string | null
  device_name?: string | null
  device_platform?: string | null
}

export interface SyncConflict {
  id: string
  project_id: string
  project_title: string
  entity_type: string
  entity_id: string
  device_name?: string | null
  client_base_revision: number
  server_revision: number
  client_operation: 'upsert' | 'delete'
  server_operation: 'upsert' | 'delete'
  client_payload?: Record<string, unknown> | null
  server_payload?: Record<string, unknown> | null
  status: 'open' | 'resolved'
  created_at: string
}
