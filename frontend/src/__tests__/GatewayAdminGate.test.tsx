import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

const client = vi.hoisted(() => ({ get: vi.fn() }))
const gatewayApi = vi.hoisted(() => ({
  getGatewayAdminSession: vi.fn(),
  getGatewayStatus: vi.fn(),
  loginGatewayAdmin: vi.fn(),
}))

vi.mock('../api/client', () => ({ apiClient: client }))
vi.mock('../features/gateway/api', () => gatewayApi)

import GatewayAdminGate from '../features/gateway/GatewayAdminGate'

const launcher = (headless: boolean) => ({
  data: {
    data: {
      gateway_enabled: headless,
      gateway_runtime_active: headless,
      gateway_headless: headless,
      gateway_advertised_url: '',
      gateway_allowed_hosts: '',
    },
  },
})

describe('GatewayAdminGate', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.localStorage.clear()
    window.sessionStorage.clear()
  })

  it('does not gate the desktop application', async () => {
    client.get.mockResolvedValue(launcher(false))
    render(<GatewayAdminGate><div>桌面作品库</div></GatewayAdminGate>)

    expect(await screen.findByText('桌面作品库')).toBeInTheDocument()
    expect(gatewayApi.getGatewayAdminSession).not.toHaveBeenCalled()
    expect(gatewayApi.getGatewayStatus).not.toHaveBeenCalled()
  })

  it('unlocks a headless Gateway without storing its bootstrap key', async () => {
    client.get.mockResolvedValue(launcher(true))
    gatewayApi.getGatewayAdminSession.mockResolvedValue({ authenticated: false })
    gatewayApi.getGatewayStatus.mockResolvedValue({ cursor: 1 })
    gatewayApi.loginGatewayAdmin.mockResolvedValue({
      device_role: 'owner',
      expires_at: '2026-07-29T20:00:00Z',
    })

    render(<GatewayAdminGate><div>Gateway 工作台</div></GatewayAdminGate>)

    expect(await screen.findByText('解锁自己的创作中枢')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Gateway 管理口令'), {
      target: { value: 'private-bootstrap-key' },
    })
    fireEvent.click(screen.getByRole('button', { name: /验证并进入/ }))

    await waitFor(() => expect(gatewayApi.loginGatewayAdmin).toHaveBeenCalledWith('private-bootstrap-key'))
    expect(await screen.findByText('Gateway 工作台')).toBeInTheDocument()
    expect(window.localStorage.length).toBe(0)
    expect(window.sessionStorage.length).toBe(0)
  })
})
