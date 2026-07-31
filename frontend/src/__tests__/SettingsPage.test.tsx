import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

const api = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
}))

vi.mock('../api/client', () => ({ apiClient: api }))
vi.mock('../components/ContextGovernanceSettingsPanel', () => ({ default: () => null }))

import SettingsPage from '../pages/SettingsPage'

const launcherSettings = {
  launch_mode: 'desktop' as const,
  update_channel: 'stable' as const,
  restart_required: true,
  browser_mode_description: 'Use the default browser.',
}

function renderSettings(extra?: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <SettingsPage embedded />
      {extra}
    </QueryClientProvider>,
  )
}

function mockInitialLoads() {
  api.get.mockImplementation((url: string) => {
    if (url === '/config/models') return Promise.resolve({ data: { data: { items: [] } } })
    if (url === '/config/global-model') return Promise.resolve({ data: { data: { provider: null, model: null } } })
    if (url === '/config/content-root') {
      return Promise.resolve({ data: { data: {
        current_path: 'D:/Siming/projects', default_path: 'D:/Siming/projects', is_default: true,
        exists: true, is_empty: true,
      } } })
    }
    if (url === '/config/launcher') return Promise.resolve({ data: { data: launcherSettings } })
    return Promise.resolve({ data: { data: {} } })
  })
}

function mockCustomModelConfig() {
  api.get.mockImplementation((url: string) => {
    if (url === '/config/models') return Promise.resolve({ data: { data: { items: [{
      id: 'vendor-config',
      provider: 'vendor',
      default_model: 'legacy-model',
      base_url_override: 'https://api.vendor.example',
      api_protocol: 'auto',
      provider_type: 'api',
      readiness_status: 'unverified',
      readiness_message: '待验证',
      is_usable: false,
      is_global_default: false,
    }] } } })
    if (url === '/config/global-model') return Promise.resolve({ data: { data: { provider: null, model: null } } })
    if (url === '/config/content-root') return Promise.resolve({ data: { data: {
      current_path: 'D:/Siming/projects', default_path: 'D:/Siming/projects', is_default: true,
      exists: true, is_empty: true,
    } } })
    if (url === '/config/launcher') return Promise.resolve({ data: { data: launcherSettings } })
    return Promise.resolve({ data: { data: {} } })
  })
}

describe('SettingsPage startup and update controls', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockInitialLoads()
    api.put.mockImplementation((_url: string, payload: object) => Promise.resolve({
      data: { data: { ...launcherSettings, ...payload } },
    }))
    api.post.mockResolvedValue({ data: { data: {
      current_version: '2.8.0',
      update_channel: 'stable',
      automatic_updates: false,
      update_available: true,
      update: { version: '2.8.0', channel: 'stable', source: 'https://example.test/release', download_url: 'https://example.test/Siming.exe', sha256_available: true },
      staged_update: null,
    } } })
  })

  it('does not check or download updates during initial load', async () => {
    renderSettings()

    expect(await screen.findByText('可用模型')).toBeInTheDocument()
    expect(screen.getByText('检测到但尚未可用')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: '应用与数据' }))
    expect(await screen.findByText('启动方式')).toBeInTheDocument()
    expect(screen.getByText('尚未检查更新。不会有后台下载或静默安装。')).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('saves browser mode for the next launch', async () => {
    renderSettings()

    fireEvent.click(await screen.findByRole('tab', { name: '应用与数据' }))
    const browserRadio = await screen.findByLabelText(/浏览器模式/)
    fireEvent.click(browserRadio)
    fireEvent.click(screen.getByRole('button', { name: '保存启动方式' }))

    await waitFor(() => expect(api.put).toHaveBeenCalledWith('/config/launcher', { launch_mode: 'browser' }))
  })

  it('checks for an update only after the user clicks the button', async () => {
    renderSettings()

    fireEvent.click(await screen.findByRole('tab', { name: '应用与数据' }))
    await screen.findByText('安全更新')
    fireEvent.click(screen.getByRole('button', { name: '检查更新' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/config/update/check'))
    expect(await screen.findByRole('button', { name: '下载并校验 2.8.0' })).toBeInTheDocument()
    expect(screen.getByText('发布页提供，下载后会复核')).toBeInTheDocument()
  })

  it('saves the preview channel explicitly', async () => {
    renderSettings()

    fireEvent.click(await screen.findByRole('tab', { name: '应用与数据' }))
    fireEvent.click(await screen.findByLabelText(/预览通道/))
    fireEvent.click(screen.getByRole('button', { name: '保存更新通道' }))

    await waitFor(() => expect(api.put).toHaveBeenCalledWith('/config/launcher', {
      update_channel: 'preview',
    }))
  })

  it('tests a custom Responses endpoint with the configured model instead of listing models', async () => {
    api.get.mockImplementation((url: string) => {
      if (url === '/config/models') return Promise.resolve({ data: { data: { items: [{
        id: 'yls-config',
        provider: 'yls',
        default_model: 'gpt-5.6-sol',
        base_url_override: 'https://code.example/codex',
        api_protocol: 'responses',
        provider_type: 'api',
        readiness_status: 'unverified',
        readiness_message: '待验证',
        is_usable: false,
        is_global_default: false,
      }] } } })
      if (url === '/config/global-model') return Promise.resolve({ data: { data: { provider: null, model: null } } })
      if (url === '/config/content-root') return Promise.resolve({ data: { data: {
        current_path: 'D:/Siming/projects', default_path: 'D:/Siming/projects', is_default: true,
        exists: true, is_empty: true,
      } } })
      if (url === '/config/launcher') return Promise.resolve({ data: { data: launcherSettings } })
      return Promise.resolve({ data: { data: {} } })
    })
    api.post.mockImplementation((url: string) => {
      if (url === '/config/models/test') {
        return Promise.resolve({ data: { data: { api_protocol: 'responses', base_url: 'https://code.example/codex' } } })
      }
      return Promise.resolve({ data: { data: {} } })
    })

    renderSettings()
    fireEvent.click(await screen.findByText('检测到但尚未可用'))
    fireEvent.click(await screen.findByRole('button', { name: /编辑/ }))
    fireEvent.change(await screen.findByLabelText('API Key'), { target: { value: 'secret-key' } })
    fireEvent.click(screen.getByRole('button', { name: /用当前模型真实测试/ }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/config/models/test', expect.objectContaining({
      provider: 'yls',
      api_key: 'secret-key',
      base_url_override: 'https://code.example/codex',
      api_protocol: 'responses',
      model: 'gpt-5.6-sol',
    })))
    expect(await screen.findByText('模型真实回复成功（Responses API）')).toBeInTheDocument()
  })

  it('automatically discovers models for a custom provider after credentials are complete', async () => {
    mockCustomModelConfig()
    api.post.mockImplementation((url: string) => {
      if (url === '/config/models/list') {
        return Promise.resolve({ data: { data: {
          models: [{ id: 'vendor-model', display_name: 'Vendor Model' }],
          manual_entry_required: false,
          warning: null,
        } } })
      }
      return Promise.resolve({ data: { data: {} } })
    })

    renderSettings()
    fireEvent.click(await screen.findByText('检测到但尚未可用'))
    fireEvent.click(await screen.findByRole('button', { name: /编辑/ }))
    const apiKey = await screen.findByLabelText('API Key')
    fireEvent.change(apiKey, { target: { value: 'secret-key' } })
    fireEvent.blur(apiKey)

    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/config/models/list', {
      provider: 'vendor',
      api_key: 'secret-key',
      base_url_override: 'https://api.vendor.example',
    }))
    expect(await screen.findByText('已自动拉取 1 个模型，请选择默认模型。')).toBeInTheDocument()
    fireEvent.mouseDown(screen.getByLabelText('默认模型'))
    expect(await screen.findByText('Vendor Model')).toBeInTheDocument()
  })

  it('allows manual custom model entry only after automatic discovery fails', async () => {
    mockCustomModelConfig()
    api.post.mockImplementation((url: string) => {
      if (url === '/config/models/list') return Promise.reject(new Error('HTTP 404'))
      return Promise.resolve({ data: { data: {} } })
    })

    renderSettings()
    fireEvent.click(await screen.findByText('检测到但尚未可用'))
    fireEvent.click(await screen.findByRole('button', { name: /编辑/ }))
    expect(screen.queryByPlaceholderText('例如 openai/gpt-4o-mini 或 vendor-model-name')).not.toBeInTheDocument()
    const apiKey = await screen.findByLabelText('API Key')
    fireEvent.change(apiKey, { target: { value: 'secret-key' } })
    fireEvent.blur(apiKey)

    expect(await screen.findByText(/自动拉取模型失败：HTTP 404/)).toBeInTheDocument()
    expect(screen.getByPlaceholderText('例如 openai/gpt-4o-mini 或 vendor-model-name')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /重新拉取/ })).toBeInTheDocument()
  })
})
