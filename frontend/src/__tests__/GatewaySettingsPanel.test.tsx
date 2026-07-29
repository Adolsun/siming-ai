import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

const gatewayApi = vi.hoisted(() => ({
  approveGatewayPairing: vi.fn(),
  disableProjectSync: vi.fn(),
  enableProjectSync: vi.fn(),
  getGatewayCapabilities: vi.fn(),
  getGatewayPairingStatus: vi.fn(),
  getGatewayStatus: vi.fn(),
  listGatewayDevices: vi.fn(),
  listSyncConflicts: vi.fn(),
  listSyncProjects: vi.fn(),
  loginGatewayAdmin: vi.fn(),
  resolveSyncConflict: vi.fn(),
  revokeGatewayDevice: vi.fn(),
  startGatewayPairing: vi.fn(),
}))

vi.mock('../features/gateway/api', () => gatewayApi)

import GatewaySettingsPanel from '../features/gateway/GatewaySettingsPanel'

const activeSettings = {
  gateway_enabled: true,
  gateway_runtime_active: true,
  gateway_advertised_url: '',
  gateway_allowed_hosts: '',
}

describe('GatewaySettingsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.localStorage.clear()
    window.sessionStorage.clear()
    gatewayApi.getGatewayCapabilities.mockResolvedValue({
      runtime_profile: 'gateway',
      sync_protocol_version: 1,
      gateway_authoritative: true,
      pairing_enabled: true,
      offline_replica_supported: true,
      local_ai: true,
      cli_worker: true,
      mcp: true,
      training: true,
    })
    gatewayApi.getGatewayStatus.mockResolvedValue({
      protocol_version: 1,
      cursor: 42,
      enabled_projects: 1,
      open_conflicts: 0,
      active_devices: 1,
      tombstone_retention_days: 90,
    })
    gatewayApi.listSyncProjects.mockResolvedValue([{
      project_id: 'project-1',
      title: '算法记忆之城',
      status: 'enabled',
      entity_count: 26,
      counts: { chapter: 3 },
      initial_revision: 1,
      verified_at: '2026-07-28T10:00:00Z',
      aggregate_hash: 'a'.repeat(64),
    }])
    gatewayApi.listGatewayDevices.mockResolvedValue([{
      id: 'device-1',
      name: '林岚的手机',
      platform: 'android',
      role: 'owner',
      status: 'approved',
      protocol_version: 1,
      created_at: '2026-07-28T10:00:00Z',
      last_seen_at: '2026-07-28T10:01:00Z',
    }])
    gatewayApi.listSyncConflicts.mockResolvedValue([])
    gatewayApi.loginGatewayAdmin.mockResolvedValue({
      device_role: 'owner',
      expires_at: '2026-07-28T22:00:00Z',
    })
  })

  it('keeps a disabled Gateway local and saves only after explicit action', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined)
    render(
      <GatewaySettingsPanel
        settings={{ ...activeSettings, gateway_enabled: false, gateway_runtime_active: false }}
        launcherLoading={false}
        onSave={onSave}
      />,
    )

    expect(screen.getByText('当前仍为单机模式')).toBeInTheDocument()
    expect(gatewayApi.getGatewayStatus).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('switch', { name: '启用 Gateway' }))
    fireEvent.click(screen.getByRole('button', { name: /保存 Gateway 设置/ }))

    await waitFor(() => expect(onSave).toHaveBeenCalledWith({
      gateway_enabled: true,
      gateway_advertised_url: '',
      gateway_allowed_hosts: '',
    }))
  })

  it('shows verified project, device, cursor, and empty conflict state', async () => {
    render(
      <GatewaySettingsPanel
        settings={activeSettings}
        launcherLoading={false}
        onSave={vi.fn()}
      />,
    )

    expect(await screen.findByText('算法记忆之城')).toBeInTheDocument()
    expect(screen.getByText('林岚的手机')).toBeInTheDocument()
    expect(screen.getByText('42')).toBeInTheDocument()
    expect(document.querySelector('.gateway-project-proof')).toHaveTextContent('26 项资料')
    expect(screen.getByText('没有待处理冲突')).toBeInTheDocument()
  })

  it('generates a one-time pairing QR without persisting its secret', async () => {
    gatewayApi.startGatewayPairing.mockResolvedValue({
      pairing_id: 'pairing-1',
      gateway_url: 'http://192.168.1.20:8765',
      gateway_name: '司命 Gateway',
      gateway_fingerprint: 'f'.repeat(64),
      expires_at: new Date(Date.now() + 10 * 60_000).toISOString(),
      qr_payload: { type: 'siming-gateway-pairing', pairing_secret: 'one-time-secret' },
    })
    gatewayApi.getGatewayPairingStatus.mockResolvedValue({
      pairing_id: 'pairing-1',
      status: 'created',
      expires_at: new Date(Date.now() + 10 * 60_000).toISOString(),
    })
    render(
      <GatewaySettingsPanel
        settings={activeSettings}
        launcherLoading={false}
        onSave={vi.fn()}
      />,
    )

    fireEvent.click(await screen.findByRole('button', { name: /生成配对二维码/ }))
    expect(await screen.findByText('等待手机扫描')).toBeInTheDocument()
    expect(screen.getByTitle('司命 Gateway 一次性配对二维码')).toBeInTheDocument()
    expect(window.localStorage.length).toBe(0)
  })

  it('unlocks a remote Gateway without persisting the bootstrap key', async () => {
    const unauthorized = Object.assign(new Error('需要 Gateway 管理会话'), {
      response: { status: 401 },
    })
    gatewayApi.getGatewayStatus.mockRejectedValueOnce(unauthorized)

    render(
      <GatewaySettingsPanel
        settings={activeSettings}
        launcherLoading={false}
        onSave={vi.fn()}
      />,
    )

    expect(await screen.findByText('解锁这台 Gateway 的管理页面')).toBeInTheDocument()
    const input = screen.getByLabelText('Gateway 管理口令')
    fireEvent.change(input, { target: { value: 'private-bootstrap-key' } })
    fireEvent.click(screen.getByRole('button', { name: /验证并进入/ }))

    await waitFor(() => expect(gatewayApi.loginGatewayAdmin).toHaveBeenCalledWith('private-bootstrap-key'))
    await waitFor(() => expect(screen.getByText('42')).toBeInTheDocument())
    expect(screen.queryByLabelText('Gateway 管理口令')).not.toBeInTheDocument()
    expect(window.localStorage.length).toBe(0)
    expect(window.sessionStorage.length).toBe(0)
  })
})
