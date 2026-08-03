import { useState, useEffect, useCallback } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  Card,
  Collapse,
  Typography,
  Table,
  Button,
  Modal,
  Form,
  Input,
  AutoComplete,
  Select,
  Tag,
  message,
  Space,
  Divider,
  Descriptions,
  InputNumber,
  Radio,
  Alert,
  Tabs,
} from 'antd'
import {
  PlusOutlined,
  DeleteOutlined,
  EditOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ReloadOutlined,
  FolderOpenOutlined,
  SaveOutlined,
  DesktopOutlined,
  DownloadOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import { apiClient } from '../api/client'
import { projectKeys } from '../features/projects'
import SystemNav from '../components/SystemNav'
import ContextGovernanceSettingsPanel from '../components/ContextGovernanceSettingsPanel'
import ModelReadinessBanner from '../components/ModelReadinessBanner'
import {
  type SharedModelConfig,
  useGlobalModelActions,
  useSharedModelConfigs,
} from '../shared/query/modelConfigs'
import GatewaySettingsPanel from '../features/gateway/GatewaySettingsPanel'
import type { LauncherGatewaySettings } from '../features/gateway/types'
import {
  CUSTOM_PROVIDER_VALUE,
  DEFAULT_CLI_ARGS,
  DEFAULT_CLI_COMMANDS,
  PROVIDER_ID_PATTERN,
  PROVIDER_OPTIONS,
  READINESS_LABELS,
  defaultOutputLimit,
  defaultSafetyLimits,
  fallbackModelOptions,
  isCustomProviderSelection,
  isDeepSeekModelSupported,
  isKnownProvider,
  isLocalCliProvider,
  normalizeDefaultModel,
  normalizeProviderModelOptions,
  providerColor,
  providerLabel,
  readinessColor,
  resolveProviderForSubmit,
  type ModelDiscoveryState,
  type ModelOption,
} from '../features/localModels/settingsModelOptions'
import './SettingsPage.css'

const { Title, Paragraph, Text } = Typography

type ModelConfig = SharedModelConfig

interface ContentRootSettings {
  current_path: string
  configured_path?: string | null
  default_path: string
  is_default: boolean
  exists: boolean
  is_empty: boolean
  looks_like_siming_root?: boolean
  looks_like_moshu_root?: boolean
  cancelled?: boolean
  migration?: {
    previous_root?: string
    target_root?: string
    migrated_projects?: number
    cleaned_project_folders?: number
  }
}

type LaunchMode = 'desktop' | 'browser'
type UpdateChannel = 'stable' | 'preview'

interface LauncherSettings extends LauncherGatewaySettings {
  launch_mode: LaunchMode
  update_channel: UpdateChannel
  restart_required: boolean
  browser_mode_description: string
}

interface UpdateSignature {
  valid: boolean
  status: string
  subject?: string
  thumbprint?: string
}

interface UpdateMetadata {
  version: string
  channel: UpdateChannel
  source: string
  download_url: string
  sha256_available: boolean
}

interface StagedUpdate {
  version: string
  sha256: string
  signature?: UpdateSignature | null
  ready_to_install: boolean
  error?: string
}

interface UpdateStatus {
  current_version: string
  update_channel: UpdateChannel
  update_available: boolean
  update?: UpdateMetadata | null
  staged_update?: StagedUpdate | null
  automatic_updates: boolean
  downloaded?: boolean
}

interface SettingsPageProps {
  embedded?: boolean
}

function SettingsPage({ embedded = false }: SettingsPageProps = {}) {
  const queryClient = useQueryClient()
  const modelConfigsQuery = useSharedModelConfigs()
  const { setGlobalModel: persistGlobalModel } = useGlobalModelActions()
  const configs = modelConfigsQuery.data?.items || []
  const loading = modelConfigsQuery.isLoading || modelConfigsQuery.isFetching
  const globalConfig = configs.find((config) => config.is_global_default && config.is_usable)
  const globalModel = {
    provider: globalConfig?.provider || null,
    model: globalConfig?.default_model || null,
  }
  const [modalOpen, setModalOpen] = useState(false)
  const [editingProvider, setEditingProvider] = useState<string | null>(null)
  const [form] = Form.useForm()
  const modalProvider = Form.useWatch('provider', form)

  const [modelOptions, setModelOptions] = useState<ModelOption[]>([])
  const [modelDiscovery, setModelDiscovery] = useState<ModelDiscoveryState>({ status: 'idle' })
  const [modelsLoading, setModelsLoading] = useState(false)
  const [testingConnection, setTestingConnection] = useState(false)
  const [verifyingProvider, setVerifyingProvider] = useState<string>()
  const [connectionTestResult, setConnectionTestResult] = useState<{ success: boolean; message: string } | null>(null)
  const [contentRoot, setContentRoot] = useState<ContentRootSettings | null>(null)
  const [contentRootPath, setContentRootPath] = useState('')
  const [contentRootLoading, setContentRootLoading] = useState(false)
  const [launcherSettings, setLauncherSettings] = useState<LauncherSettings | null>(null)
  const [launchMode, setLaunchMode] = useState<LaunchMode>('desktop')
  const [updateChannel, setUpdateChannel] = useState<UpdateChannel>('stable')
  const [launcherLoading, setLauncherLoading] = useState(false)
  const [updateStatus, setUpdateStatus] = useState<UpdateStatus | null>(null)
  const [checkingUpdate, setCheckingUpdate] = useState(false)
  const [downloadingUpdate, setDownloadingUpdate] = useState(false)
  const [installingUpdate, setInstallingUpdate] = useState(false)
  const [settingsSection, setSettingsSection] = useState<'ai' | 'app' | 'gateway'>('ai')

  const fetchConfigs = useCallback(async () => {
    const result = await modelConfigsQuery.refetch()
    if (result.error) {
      message.error(result.error instanceof Error ? result.error.message : '获取模型配置失败')
    }
  }, [modelConfigsQuery])

  const fetchContentRoot = useCallback(async () => {
    setContentRootLoading(true)
    try {
      const res = await apiClient.get<{ code: number; data: ContentRootSettings }>('/config/content-root')
      setContentRoot(res.data.data)
      setContentRootPath(res.data.data.current_path || res.data.data.default_path || '')
    } catch (err: any) {
      message.error(err.message || '获取小说数据目录失败')
    } finally {
      setContentRootLoading(false)
    }
  }, [])

  const fetchLauncherSettings = useCallback(async () => {
    setLauncherLoading(true)
    try {
      const res = await apiClient.get<{ code: number; data: LauncherSettings }>('/config/launcher')
      setLauncherSettings(res.data.data)
      setLaunchMode(res.data.data.launch_mode)
      setUpdateChannel(res.data.data.update_channel || 'stable')
      if (res.data.data.gateway_headless && !embedded) setSettingsSection('gateway')
    } catch (err: any) {
      message.error(err.message || '获取启动方式失败')
    } finally {
      setLauncherLoading(false)
    }
  }, [embedded])

  useEffect(() => {
    fetchContentRoot()
    fetchLauncherSettings()
  }, [fetchContentRoot, fetchLauncherSettings])

  const saveLaunchMode = async () => {
    setLauncherLoading(true)
    try {
      const res = await apiClient.put<{ code: number; data: LauncherSettings }>('/config/launcher', {
        launch_mode: launchMode,
      })
      setLauncherSettings(res.data.data)
      message.success('启动方式已保存，下次启动生效')
    } catch (err: any) {
      message.error(err.message || '保存启动方式失败')
    } finally {
      setLauncherLoading(false)
    }
  }

  const saveUpdateChannel = async () => {
    setLauncherLoading(true)
    try {
      const res = await apiClient.put<{ code: number; data: LauncherSettings }>('/config/launcher', {
        update_channel: updateChannel,
      })
      setLauncherSettings(res.data.data)
      setUpdateStatus(null)
      message.success('更新通道已保存')
    } catch (err: any) {
      message.error(err.message || '保存更新通道失败')
    } finally {
      setLauncherLoading(false)
    }
  }

  const saveGatewaySettings = async (values: Partial<LauncherGatewaySettings>) => {
    try {
      const res = await apiClient.put<{ code: number; data: LauncherSettings }>('/config/launcher', values)
      setLauncherSettings(res.data.data)
      message.success(values.gateway_enabled === false
        ? 'Gateway 关闭设置已保存，重启后生效'
        : 'Gateway 设置已保存，重启后生效')
    } catch (err: any) {
      message.error(err.message || '保存 Gateway 设置失败')
      throw err
    }
  }

  const checkForUpdates = async () => {
    setCheckingUpdate(true)
    try {
      const res = await apiClient.post<{ code: number; data: UpdateStatus }>('/config/update/check')
      setUpdateStatus(res.data.data)
      if (res.data.data.update_available) {
        message.success(`发现司命 ${res.data.data.update?.version || '新'}版本`)
      } else {
        message.info('当前已是最新版本，或暂时无法获取更新信息')
      }
    } catch (err: any) {
      message.error(err.message || '检查更新失败')
    } finally {
      setCheckingUpdate(false)
    }
  }

  const downloadUpdate = () => {
    if (!updateStatus?.update) return
    Modal.confirm({
      title: `下载司命 ${updateStatus.update.version}？`,
      content: '将下载更新包，并在本机校验 SHA256 和代码签名。校验失败的文件会被删除，不会安装。',
      okText: '下载并校验',
      cancelText: '取消',
      onOk: async () => {
        setDownloadingUpdate(true)
        try {
          const res = await apiClient.post<{ code: number; data: UpdateStatus }>('/config/update/download')
          setUpdateStatus(res.data.data)
          message.success('更新已下载并通过 SHA256 与签名校验，可以安装')
        } catch (err: any) {
          message.error(err.message || '更新未通过安全校验，已停止安装')
        } finally {
          setDownloadingUpdate(false)
        }
      },
    })
  }

  const installUpdate = () => {
    if (!updateStatus?.staged_update?.ready_to_install) return
    Modal.confirm({
      title: '安装已验证的更新？',
      content: '司命会关闭当前窗口，由已验证的新版本替换旧程序后重新启动。未验证的更新不会被安装。',
      okText: '安装并重启',
      cancelText: '取消',
      onOk: async () => {
        setInstallingUpdate(true)
        try {
          await apiClient.post('/config/update/install')
          message.success('更新已安排，司命即将重启')
        } catch (err: any) {
          setInstallingUpdate(false)
          message.error(err.message || '安装更新失败')
        }
      },
    })
  }

  const applyContentRootResponse = (settings: ContentRootSettings, successText: string) => {
    setContentRoot(settings)
    setContentRootPath(settings.current_path || settings.default_path || '')
    const migrated = settings.migration?.migrated_projects
    if (typeof migrated === 'number') {
      message.success(`${successText}，已迁移 ${migrated} 个作品`)
    } else {
      message.success(successText)
    }
    void queryClient.invalidateQueries({ queryKey: projectKeys.all })
  }

  const saveContentRoot = async () => {
    const path = contentRootPath.trim()
    if (!path) {
      message.warning('请填写小说数据目录')
      return
    }
    Modal.confirm({
      title: '切换小说数据目录',
      content: '新目录必须为空，或已经是司命小说数据目录。保存后会把现有作品资料迁移到新目录。',
      okText: '保存并迁移',
      onOk: async () => {
        setContentRootLoading(true)
        try {
          const res = await apiClient.put<{ code: number; data: ContentRootSettings }>('/config/content-root', { path })
          applyContentRootResponse(res.data.data, '小说数据目录已更新')
        } catch (err: any) {
          message.error(err.message || '更新小说数据目录失败')
        } finally {
          setContentRootLoading(false)
        }
      },
    })
  }

  const pickContentRoot = async () => {
    setContentRootLoading(true)
    try {
      const res = await apiClient.post<{ code: number; data: ContentRootSettings }>('/config/content-root/pick')
      if (res.data.data.cancelled) {
        setContentRoot(res.data.data)
        setContentRootPath(res.data.data.current_path || res.data.data.default_path || '')
        message.info('已取消选择')
        return
      }
      applyContentRootResponse(res.data.data, '小说数据目录已更新')
    } catch (err: any) {
      message.error(err.message || '选择小说数据目录失败')
    } finally {
      setContentRootLoading(false)
    }
  }

  const handleAddOrEdit = (provider?: string) => {
    setConnectionTestResult(null)
    setModelDiscovery({ status: 'idle' })
    if (provider) {
      const cfg = configs.find((c) => c.provider === provider)
      if (cfg) {
        setEditingProvider(provider)
        const defaultModel = normalizeDefaultModel(cfg.provider, cfg.default_model)
        const knownProvider = isKnownProvider(cfg.provider)
        setModelOptions(knownProvider
          ? fallbackModelOptions(cfg.provider)
          : [{ id: defaultModel, display_name: defaultModel }])
        if (!knownProvider) {
          setModelDiscovery({ status: 'success', message: '已保留当前模型；可直接使用已保存密钥刷新模型列表。' })
        }
        form.setFieldsValue({
          provider: knownProvider ? cfg.provider : CUSTOM_PROVIDER_VALUE,
          custom_provider: knownProvider ? undefined : cfg.provider,
          default_model: defaultModel,
          base_url_override: cfg.base_url_override || '',
          api_protocol: cfg.api_protocol || 'auto',
          provider_type: cfg.provider_type || (isLocalCliProvider(cfg.provider) ? 'local_cli' : 'api'),
          cli_command: cfg.cli_command || DEFAULT_CLI_COMMANDS[cfg.provider] || '',
          cli_args: cfg.cli_args || DEFAULT_CLI_ARGS[cfg.provider] || '',
          api_key: '',
          max_output_tokens: cfg.max_output_tokens || cfg.effective_max_output_tokens || defaultOutputLimit(cfg.provider, defaultModel),
          deconstruct_input_char_limit: cfg.deconstruct_input_char_limit || cfg.effective_deconstruct_input_char_limit || defaultOutputLimit(cfg.provider, defaultModel),
          deconstruct_item_char_limit: cfg.deconstruct_item_char_limit || cfg.effective_deconstruct_item_char_limit || defaultOutputLimit(cfg.provider, defaultModel),
        })
        void fetchModels(provider)
      }
    } else {
      setEditingProvider(null)
      setModelOptions([])
      setModelDiscovery({ status: 'idle' })
      form.resetFields()
    }
    setModalOpen(true)
  }

  const handleSubmit = async (values: any) => {
    try {
      const provider = resolveProviderForSubmit(values)
      if (!provider) {
        message.error('请填写自定义提供商标识')
        return
      }
      if (!PROVIDER_ID_PATTERN.test(provider)) {
        message.error('提供商标识只能包含字母、数字、下划线和短横线')
        return
      }
      const isCli = isLocalCliProvider(provider)
      if (isCustomProviderSelection(values.provider) && !values.base_url_override) {
        message.error('自定义 OpenAI 兼容提供商必须填写 API 端点')
        return
      }
      if (isCli && provider === 'custom_cli' && !values.cli_command) {
        message.error('请填写本机 CLI 命令')
        return
      }

      const defaultModel = normalizeDefaultModel(provider, values.default_model)
      if (provider === 'deepseek' && !isDeepSeekModelSupported(defaultModel)) {
        message.error('DeepSeek 当前支持 deepseek-v4-pro 或 deepseek-v4-flash，请重新选择')
        return
      }
      await apiClient.post('/config/models', {
        provider,
        api_key: isCli ? undefined : values.api_key,
        default_model: defaultModel,
        base_url_override: isCli ? null : values.base_url_override || null,
        api_protocol: isCli ? 'chat_completions' : values.api_protocol || 'auto',
        provider_type: isCli ? 'local_cli' : 'api',
        cli_command: isCli ? values.cli_command || DEFAULT_CLI_COMMANDS[provider] || null : null,
        cli_args: isCli ? values.cli_args || DEFAULT_CLI_ARGS[provider] || null : null,
        max_output_tokens: values.max_output_tokens || null,
        deconstruct_input_char_limit: values.deconstruct_input_char_limit || null,
        deconstruct_item_char_limit: values.deconstruct_item_char_limit || null,
      })
      message.success('配置已保存')
      setModalOpen(false)
      form.resetFields()
      fetchConfigs()
    } catch (err: any) {
      message.error(err.message || '保存配置失败')
    }
  }

  const handleDelete = async (provider: string) => {
    Modal.confirm({
      title: '确认删除',
      content: `确定要删除 ${providerLabel(provider)} 的配置吗？`,
      okText: '删除',
      okType: 'danger',
      onOk: async () => {
        try {
          await apiClient.delete(`/config/models/${provider}`)
          message.success('配置已删除')
          fetchConfigs()
        } catch (err: any) {
          message.error(err.message || '删除配置失败')
        }
      },
    })
  }

  const fetchModels = async (providerOverride?: string) => {
    const values = form.getFieldsValue()
    const provider = providerOverride
      ? (isCustomProviderSelection(providerOverride) ? String(values.custom_provider || '').trim() : providerOverride)
      : resolveProviderForSubmit(values)
    const apiKey = form.getFieldValue('api_key')
    if (!provider) return
    const isCli = isLocalCliProvider(provider)
    const isCustom = isCustomProviderSelection(form.getFieldValue('provider'))
    const baseUrl = form.getFieldValue('base_url_override') || undefined
    if (isCli) {
      setModelsLoading(true)
      setModelDiscovery({ status: 'idle', message: provider === 'opencode_cli' ? '正在运行 OpenCode CLI 获取可用模型…' : '正在通过本机 CLI 获取可用模型…' })
      setModelOptions(fallbackModelOptions(provider))
      try {
        const res = await apiClient.post<{ code: number; data: { models: ModelOption[] } }>(
          '/config/models/list',
          {
            provider,
            cli_command: form.getFieldValue('cli_command') || DEFAULT_CLI_COMMANDS[provider],
            cli_args: form.getFieldValue('cli_args') || DEFAULT_CLI_ARGS[provider],
          }
        )
        const options = normalizeProviderModelOptions(provider, res.data.data.models || [])
        setModelOptions(options)
        setModelDiscovery({
          status: 'success',
          message: provider === 'opencode_cli'
            ? `已由司命运行 OpenCode CLI，获取到 ${options.length} 个可用模型。`
            : `已从本机 CLI 获取到 ${options.length} 个模型。`,
        })
      } catch (err: any) {
        setModelOptions(fallbackModelOptions(provider))
        setModelDiscovery({ status: 'manual', message: `CLI 模型发现失败：${err.message || '命令不可用'}。仍可手动填写模型名。` })
      } finally {
        setModelsLoading(false)
      }
      return
    }
    if (isCustom && !baseUrl) {
      setModelOptions([])
      setModelDiscovery({ status: 'idle', message: '填写 API 端点和 API Key 后，将自动拉取模型列表。' })
      return
    }
    const savedProvider = providerOverride || editingProvider
    const hasSavedApiKey = Boolean(savedProvider && configs.find((item) => item.provider === savedProvider)?.api_key_configured)
    if (!apiKey && !hasSavedApiKey) {
      setModelOptions(fallbackModelOptions(provider))
      if (isCustom) {
        setModelDiscovery({ status: 'idle', message: '填写 API 端点和 API Key 后，将自动拉取模型列表。' })
      }
      return
    }

    setModelsLoading(true)
    setModelOptions(fallbackModelOptions(provider))
    if (isCustom) {
      setModelDiscovery({ status: 'idle', message: '正在自动拉取模型列表…' })
    }
    try {
      const res = await apiClient.post<{
        code: number
        data: { models: ModelOption[]; manual_entry_required?: boolean; warning?: string | null }
      }>(
        '/config/models/list',
        {
          provider,
          api_key: apiKey || undefined,
          base_url_override: baseUrl,
        }
      )
      const options = normalizeProviderModelOptions(provider, res.data.data.models || [])
      setModelOptions(options)
      if (isCustom) {
        if (res.data.data.manual_entry_required || options.length === 0) {
          setModelDiscovery({
            status: 'manual',
            message: res.data.data.warning || '服务商未返回模型列表，请手动填写支持的模型名。',
          })
        } else {
          setModelDiscovery({ status: 'success', message: `已自动拉取 ${options.length} 个模型，请选择默认模型。` })
        }
      }
    } catch (err: any) {
      setModelOptions(fallbackModelOptions(provider))
      if (isCustom) {
        setModelDiscovery({
          status: 'manual',
          message: `自动拉取模型失败：${err.message || '服务暂时不可用'}。你仍可手动填写模型名。`,
        })
      }
    } finally {
      setModelsLoading(false)
    }
  }

  const testConnection = async () => {
    const values = form.getFieldsValue()
    const provider = resolveProviderForSubmit(values)
    const isCli = isLocalCliProvider(provider)
    const apiKey = form.getFieldValue('api_key')
    const hasSavedApiKey = Boolean(editingProvider && configs.find((item) => item.provider === editingProvider)?.api_key_configured)
    if (!provider || (!isCli && !apiKey && !hasSavedApiKey)) {
      message.warning('请先选择提供商并输入 API Key')
      return
    }
    const baseUrl = form.getFieldValue('base_url_override') || undefined
    if (!isCli && !isKnownProvider(provider) && !baseUrl) {
      message.warning('自定义 OpenAI 兼容提供商必须填写 API 端点')
      return
    }
    if (!values.default_model) {
      message.warning('请先填写要实际调用的模型名')
      return
    }

    setTestingConnection(true)
    setConnectionTestResult(null)
    try {
      const response = await apiClient.post<{
        code: number
        data: { api_protocol?: 'chat_completions' | 'responses'; base_url?: string }
      }>('/config/models/test', {
        provider,
        api_key: isCli ? undefined : apiKey || undefined,
        base_url_override: isCli ? undefined : baseUrl,
        api_protocol: isCli ? undefined : values.api_protocol || 'auto',
        cli_command: isCli ? values.cli_command || DEFAULT_CLI_COMMANDS[provider] : undefined,
        cli_args: isCli ? values.cli_args || DEFAULT_CLI_ARGS[provider] : undefined,
        model: values.default_model,
      })
      const protocol = response.data.data?.api_protocol
      const protocolLabel = protocol === 'responses' ? 'Responses API' : 'Chat Completions'
      setConnectionTestResult({
        success: true,
        message: isCli ? '本机 CLI 真实对话成功' : `模型真实回复成功（${protocolLabel}）`,
      })
    } catch (err: any) {
      setConnectionTestResult({ success: false, message: err.message || '连接失败' })
    } finally {
      setTestingConnection(false)
    }
  }

  const verifySavedConfig = async (provider: string) => {
    setVerifyingProvider(provider)
    try {
      const response = await apiClient.post<{ code: number; message: string; data: { became_global_default: boolean } }>(
        `/config/models/${provider}/verify`,
      )
      message.success(response.data.message || '模型已经通过真实对话测试')
      await fetchConfigs()
    } catch (err: any) {
      message.error(err.message || '真实对话测试失败')
      await fetchConfigs()
    } finally {
      setVerifyingProvider(undefined)
    }
  }

  const handleSetGlobal = async (provider: string) => {
    const config = configs.find((item) => item.provider === provider)
    if (!config) return
    try {
      const model = normalizeDefaultModel(provider, config.default_model)
      await persistGlobalModel(provider, model)
      message.success('全局默认模型已设置')
    } catch (err: any) {
      message.error(err.message || '设置全局默认模型失败')
    }
  }

  const columns = [
    {
      title: '提供商',
      dataIndex: 'provider',
      key: 'provider',
      render: (v: string) => (
        <Tag color={providerColor(v)}>{providerLabel(v)}</Tag>
      ),
    },
    {
      title: '默认模型',
      dataIndex: 'default_model',
      key: 'default_model',
      render: (value: string, record: ModelConfig) => normalizeDefaultModel(record.provider, value),
    },
    {
      title: '可用状态',
      dataIndex: 'readiness_status',
      key: 'readiness_status',
      render: (status: ModelConfig['readiness_status'], record: ModelConfig) => (
        <Space direction="vertical" size={0}>
          <Tag color={readinessColor(status)}>{READINESS_LABELS[status]}</Tag>
          <Text type="secondary" className="settings-readiness-message">{record.readiness_message}</Text>
        </Space>
      ),
    },
    {
      title: '凭据',
      key: 'credential',
      render: (_: unknown, record: ModelConfig) => (
        isLocalCliProvider(record.provider) ? '本机工具，无需 API Key' : '已加密保存'
      ),
    },
    {
      title: '全局默认',
      dataIndex: 'is_global_default',
      key: 'is_global_default',
      render: (_v: boolean, record: ModelConfig) =>
        globalModel.provider === record.provider
          ? <Tag icon={<CheckCircleOutlined />} color="success">是</Tag>
          : <span>—</span>,
    },
    {
      title: '操作',
      key: 'action',
      render: (_: any, record: ModelConfig) => (
        <Space wrap>
          {!record.is_usable && (
            <Button
              type="primary"
              icon={<ReloadOutlined />}
              loading={verifyingProvider === record.provider}
              onClick={() => void verifySavedConfig(record.provider)}
            >
              测试并启用
            </Button>
          )}
          {record.is_usable && globalModel.provider !== record.provider && (
            <Button onClick={() => void handleSetGlobal(record.provider)}>设为默认</Button>
          )}
          <Button
            type="text"
            icon={<EditOutlined />}
            onClick={() => handleAddOrEdit(record.provider)}
          >
            编辑
          </Button>
          <Button
            type="text"
            danger
            icon={<DeleteOutlined />}
            onClick={() => handleDelete(record.provider)}
          >
            删除
          </Button>
        </Space>
      ),
    },
  ]

  const readyConfigs = configs.filter((config) => config.is_usable)
  const pendingConfigs = configs.filter((config) => !config.is_usable)

  const defaultModelOptions = modelOptions.length > 0 ? modelOptions : fallbackModelOptions(modalProvider)
  const customModelSelection = isCustomProviderSelection(modalProvider)
  const customManualEntry = customModelSelection && modelDiscovery.status === 'manual'
  const providerOptions = launcherSettings?.gateway_headless
    ? PROVIDER_OPTIONS.filter((option) => !isLocalCliProvider(option.value))
    : PROVIDER_OPTIONS

  return (
    <div className="settings-page">
      {!embedded && <SystemNav current="settings" />}
      <header className="siming-section-header settings-heading">
        <div>
          <span className="siming-section-kicker">系统控制</span>
          <Title level={3}><SettingOutlined /> 系统设置</Title>
          <p className="siming-section-description">先连接一个可用模型；启动、更新和数据目录只在需要时调整。</p>
        </div>
      </header>
      <Tabs
        className="settings-tabs"
        activeKey={settingsSection}
        onChange={(key) => setSettingsSection(key as 'ai' | 'app' | 'gateway')}
        items={[
          { key: 'ai', label: '模型与 AI' },
          { key: 'gateway', label: '跨设备 Gateway' },
          { key: 'app', label: '应用与数据' },
        ].filter((item) => !launcherSettings?.gateway_headless || item.key !== 'app')}
      />

      {settingsSection === 'gateway' && (
        <GatewaySettingsPanel
          settings={launcherSettings}
          launcherLoading={launcherLoading}
          onSave={saveGatewaySettings}
        />
      )}

      {settingsSection === 'app' && <>
      <Card className="settings-card" title={<span><DesktopOutlined /> 启动方式</span>} loading={launcherLoading && !launcherSettings}>
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Paragraph style={{ margin: 0 }}>
            选择司命下次启动时打开界面的方式。切换不会重启当前程序，也不会影响作品和模型配置。
          </Paragraph>
          <Radio.Group value={launchMode} onChange={(event) => setLaunchMode(event.target.value)}>
            <Space direction="vertical" size={8}>
              <Radio value="desktop">
                <Text strong>桌面窗口</Text>
                <Text type="secondary"> 使用内嵌 WebView2 打开司命。</Text>
              </Radio>
              <Radio value="browser">
                <Text strong>浏览器模式</Text>
                <Text type="secondary"> 司命只启动本地服务，并用默认浏览器打开，不启动内嵌 WebView2。</Text>
              </Radio>
            </Space>
          </Radio.Group>
          <Space wrap>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              aria-label="保存启动方式"
              loading={launcherLoading}
              disabled={launcherSettings?.launch_mode === launchMode}
              onClick={saveLaunchMode}
            >
              保存启动方式
            </Button>
            <Text type="secondary">当前保存：{launcherSettings?.launch_mode === 'browser' ? '浏览器模式' : '桌面窗口'}</Text>
          </Space>
          <Alert
            showIcon
            type="info"
            message="浏览器模式可避免由司命启动 Edge WebView2"
            description="它不能阻止浏览器自身更新，但能避免 Siming.exe 启动内嵌 WebView2 后被安全软件按父进程关联提示。"
          />
        </Space>
      </Card>

      <Card className="settings-card" title={<span><SafetyCertificateOutlined /> 安全更新</span>}>
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Paragraph style={{ margin: 0 }}>
            司命不会在启动时自动检查、下载或替换程序。只有你点击下方按钮后，才会检查版本；下载后必须通过 SHA256 和 Windows 代码签名校验，才能安装。
          </Paragraph>
          <Radio.Group
            value={updateChannel}
            onChange={(event) => {
              setUpdateChannel(event.target.value)
              setUpdateStatus(null)
            }}
          >
            <Space direction="vertical" size={8}>
              <Radio value="stable">
                <Text strong>稳定通道</Text>
                <Text type="secondary"> 只接收正式版本，适合日常创作。</Text>
              </Radio>
              <Radio value="preview">
                <Text strong>预览通道</Text>
                <Text type="secondary"> 可接收 alpha、beta 和 RC，用于参与 3.0 测试。</Text>
              </Radio>
            </Space>
          </Radio.Group>
          <Space wrap>
            <Button
              icon={<SaveOutlined />}
              aria-label="保存更新通道"
              loading={launcherLoading}
              disabled={launcherSettings?.update_channel === updateChannel}
              onClick={saveUpdateChannel}
            >
              保存更新通道
            </Button>
            <Button aria-label="检查更新" icon={<ReloadOutlined />} loading={checkingUpdate} onClick={checkForUpdates}>
              检查更新
            </Button>
            {updateStatus?.update_available && updateStatus.update && (
              <Button
                type="primary"
                icon={<DownloadOutlined />}
                aria-label={`下载并校验 ${updateStatus.update.version}`}
                loading={downloadingUpdate}
                disabled={!updateStatus.update.sha256_available}
                onClick={downloadUpdate}
              >
                下载并校验 {updateStatus.update.version}
              </Button>
            )}
            {updateStatus?.staged_update?.ready_to_install && (
              <Button
                type="primary"
                icon={<SafetyCertificateOutlined />}
                aria-label="安装并重启"
                loading={installingUpdate}
                onClick={installUpdate}
              >
                安装并重启
              </Button>
            )}
          </Space>
          {!updateStatus && (
            <Text type="secondary">尚未检查更新。不会有后台下载或静默安装。</Text>
          )}
          {updateStatus && !updateStatus.update_available && !updateStatus.staged_update && (
            <Text type="secondary">已检查：当前版本 {updateStatus.current_version} 暂无可验证更新。</Text>
          )}
          {updateStatus?.update_available && updateStatus.update && (
            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label="可用版本">{updateStatus.update.version}</Descriptions.Item>
              <Descriptions.Item label="更新通道">
                {updateStatus.update.channel === 'preview' ? '预览通道' : '稳定通道'}
              </Descriptions.Item>
              <Descriptions.Item label="SHA256">
                {updateStatus.update.sha256_available ? '发布页提供，下载后会复核' : '发布页未提供，司命不会下载或安装'}
              </Descriptions.Item>
              <Descriptions.Item label="代码签名">下载后必须验证为可信签名</Descriptions.Item>
            </Descriptions>
          )}
          {updateStatus?.staged_update && (
            <Alert
              showIcon
              type={updateStatus.staged_update.ready_to_install ? 'success' : 'warning'}
              message={updateStatus.staged_update.ready_to_install ? '更新已验证，可以由你确认安装' : '已下载的更新需要重新校验'}
              description={updateStatus.staged_update.ready_to_install
                ? `版本 ${updateStatus.staged_update.version}，SHA256：${updateStatus.staged_update.sha256}`
                : updateStatus.staged_update.error || '请重新下载更新。'}
            />
          )}
        </Space>
      </Card>

      <Card className="settings-card" title={<span><FolderOpenOutlined /> 小说数据目录</span>} loading={contentRootLoading && !contentRoot}>
        <Descriptions size="small" column={1} bordered>
          <Descriptions.Item label="当前目录">
            <Text code copyable>{contentRoot?.current_path || '未加载'}</Text>
          </Descriptions.Item>
          <Descriptions.Item label="默认目录">
            <Text code copyable>{contentRoot?.default_path || '未加载'}</Text>
          </Descriptions.Item>
          <Descriptions.Item label="状态">
            <Space wrap>
              <Tag color={contentRoot?.is_default ? 'default' : 'blue'}>
                {contentRoot?.is_default ? '使用默认目录' : '已指定目录'}
              </Tag>
              <Tag color={contentRoot?.exists ? 'success' : 'warning'}>
                {contentRoot?.exists ? '目录存在' : '目录未创建'}
              </Tag>
              <Tag color={contentRoot?.is_empty ? 'default' : 'green'}>
                {contentRoot?.is_empty ? '当前为空' : (contentRoot?.looks_like_siming_root || contentRoot?.looks_like_moshu_root) ? '司命数据目录' : '已有文件'}
              </Tag>
            </Space>
          </Descriptions.Item>
        </Descriptions>

        <Divider style={{ margin: '16px 0' }} />

        <Space.Compact style={{ width: '100%' }}>
          <Input
            value={contentRootPath}
            onChange={(event) => setContentRootPath(event.target.value)}
            placeholder="选择或填写一个空文件夹路径"
          />
          <Button icon={<FolderOpenOutlined />} loading={contentRootLoading} onClick={pickContentRoot}>
            选择文件夹
          </Button>
          <Button type="primary" icon={<SaveOutlined />} loading={contentRootLoading} onClick={saveContentRoot}>
            保存
          </Button>
        </Space.Compact>

        <p style={{ marginTop: 12, color: 'var(--ant-color-text-secondary)' }}>
          未指定时自动使用默认目录。切换目录会迁移现有作品资料；为了避免混入无关文件，新目录必须为空，或是已经由司命创建过的小说数据目录。
        </p>
      </Card>
      </>}

      {settingsSection === 'ai' && <>
      {launcherSettings?.gateway_headless && (
        <Alert
          showIcon
          type="info"
          message="Docker Gateway 只运行云端模型"
          description="本地模型、OpenCode 等本机 CLI、MCP 与训练能力仍留在桌面端；容器中只保存你主动配置的云端 API。"
          style={{ marginBottom: 16 }}
        />
      )}
      <ModelReadinessBanner
        ready={Boolean(globalModel.provider)}
        detail={globalModel.provider && globalModel.model
          ? `当前默认：${providerLabel(globalModel.provider)} · ${normalizeDefaultModel(globalModel.provider, globalModel.model)}`
          : '请对一个配置执行真实对话测试；仅检测到工具不代表已经登录或有可用额度。'}
      />

      <Card
        className="settings-card"
        title="可用模型"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={() => handleAddOrEdit()}>
            添加配置
          </Button>
        }
      >
        <Table
          dataSource={readyConfigs}
          columns={columns}
          rowKey="id"
          loading={loading}
          pagination={false}
          locale={{ emptyText: '还没有通过真实对话测试的模型' }}
          scroll={{ x: 900 }}
        />
      </Card>

      <Collapse
        className="settings-card settings-pending-models"
        items={[{
          key: 'pending-models',
          label: <Space><Text strong>检测到但尚未可用</Text><Tag>{pendingConfigs.length}</Tag></Space>,
          children: (
            <>
              <Paragraph type="secondary">
                这里的 CLI 或 API 配置尚未验证登录、模型和额度。测试成功前不会出现在助手、新书或写作模型列表中。
              </Paragraph>
              <Table
                dataSource={pendingConfigs}
                columns={columns}
                rowKey="id"
                loading={loading}
                pagination={false}
                locale={{ emptyText: '没有待验证的配置' }}
                scroll={{ x: 900 }}
              />
            </>
          ),
        }]}
      />

      <Collapse
        className="settings-card"
        items={[{
          key: 'advanced-ai',
          label: '高级设置：上下文与技术参数',
          children: <ContextGovernanceSettingsPanel />,
        }]}
      />
      </>}

      <Modal
        title={editingProvider ? `编辑 ${providerLabel(editingProvider)} 配置` : '添加模型配置'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}
        destroyOnHidden
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={handleSubmit}
          style={{ marginTop: 16 }}
        >
          <Form.Item
            name="provider"
            label="提供商"
            rules={[{ required: true, message: '请选择提供商' }]}
          >
            <Select
              placeholder="选择提供商"
              disabled={!!editingProvider}
              onChange={(provider) => {
                const fallback = fallbackModelOptions(provider)
                setModelOptions(fallback)
                setModelDiscovery({ status: 'idle' })
                setConnectionTestResult(null)
                const nextModel = isCustomProviderSelection(provider) ? undefined : fallback[0]?.id
                form.setFieldValue('default_model', nextModel)
                form.setFieldsValue({
                  ...defaultSafetyLimits(provider, nextModel),
                  provider_type: isLocalCliProvider(provider) ? 'local_cli' : 'api',
                  cli_command: isLocalCliProvider(provider) ? DEFAULT_CLI_COMMANDS[provider] || '' : undefined,
                  cli_args: isLocalCliProvider(provider) ? DEFAULT_CLI_ARGS[provider] || '' : undefined,
                  api_key: isLocalCliProvider(provider) ? undefined : form.getFieldValue('api_key'),
                  base_url_override: isLocalCliProvider(provider) ? undefined : form.getFieldValue('base_url_override'),
                  api_protocol: isLocalCliProvider(provider) ? 'chat_completions' : 'auto',
                })
                if (isLocalCliProvider(provider) || form.getFieldValue('api_key')) {
                  void fetchModels(provider)
                }
              }}
              options={providerOptions}
            />
          </Form.Item>

          {isCustomProviderSelection(modalProvider) && (
            <Form.Item
              name="custom_provider"
              label="自定义提供商标识"
              extra="用于保存和选择模型，例如 openrouter、siliconflow、moonshot。只能包含字母、数字、下划线和短横线。"
              rules={[
                { required: true, message: '请填写自定义提供商标识' },
                {
                  pattern: PROVIDER_ID_PATTERN,
                  message: '只能包含字母、数字、下划线和短横线',
                },
              ]}
            >
              <Input
                disabled={!!editingProvider}
                placeholder="例如 openrouter"
                onBlur={() => {
                  if (form.getFieldValue('api_key')) {
                    fetchModels()
                  }
                }}
              />
            </Form.Item>
          )}

          {!isLocalCliProvider(modalProvider) && (
          <Form.Item
            name="api_key"
            label="API Key"
            extra={editingProvider ? '密钥已加密保存。留空会继续使用原密钥；只有输入新值才会替换。' : '密钥将在本机加密存储。'}
            rules={[{ required: !editingProvider, message: '请输入 API Key' }]}
          >
            <Input.Password
              placeholder={editingProvider ? '已保存，留空继续使用' : '输入 API Key（将被加密存储）'}
              onBlur={() => {
                if (form.getFieldValue('provider')) {
                  fetchModels()
                }
              }}
            />
          </Form.Item>
          )}

          {!isLocalCliProvider(modalProvider) && (
          <>
          <Form.Item
            name="base_url_override"
            label={customModelSelection ? 'API 端点' : '自定义 API 端点（可选）'}
            rules={[
              {
                required: customModelSelection,
                message: '自定义 OpenAI 兼容提供商必须填写 API 端点',
              },
            ]}
          >
            <Input
              placeholder="https://api.example.com/v1"
              onBlur={() => {
                if (customModelSelection && form.getFieldValue('api_key')) {
                  void fetchModels()
                }
              }}
            />
          </Form.Item>
          <Form.Item
            name="api_protocol"
            label="API 协议"
            initialValue="auto"
            extra="推荐自动识别。若服务商文档写有 wire_api = responses、Responses API 或 Codex API，可直接选择 Responses API。"
          >
            <Select
              options={[
                { value: 'auto', label: '自动识别（推荐）' },
                { value: 'chat_completions', label: 'Chat Completions' },
                { value: 'responses', label: 'Responses API' },
              ]}
            />
          </Form.Item>
          {customModelSelection && (
            <Alert
              showIcon
              type={modelDiscovery.status === 'manual' ? 'warning' : modelDiscovery.status === 'success' ? 'success' : 'info'}
              message={modelsLoading ? '正在自动拉取模型列表…' : modelDiscovery.message || '填写 API 端点和 API Key 后，将自动拉取模型列表。'}
              action={modelDiscovery.status === 'manual' ? (
                <Button size="small" icon={<ReloadOutlined />} onClick={() => void fetchModels()}>
                  重新拉取
                </Button>
              ) : undefined}
              style={{ marginBottom: 16 }}
            />
          )}
          </>
          )}

          {isLocalCliProvider(modalProvider) && (
            <>
              <Alert
                showIcon
                type={modelDiscovery.status === 'manual' ? 'warning' : modelDiscovery.status === 'success' ? 'success' : 'info'}
                message={modelsLoading ? '正在获取 CLI 模型列表…' : modelDiscovery.message || '司命可以直接运行本机 CLI 获取可用模型。'}
                action={(
                  <Button size="small" icon={<ReloadOutlined />} loading={modelsLoading} onClick={() => void fetchModels()}>
                    {modalProvider === 'opencode_cli' ? '刷新 OpenCode 模型' : '刷新 CLI 模型'}
                  </Button>
                )}
                style={{ marginBottom: 16 }}
              />
              <Form.Item
                name="cli_command"
                label="本机 CLI 命令"
                extra="例如 claude、codex、opencode，或完整可执行文件路径。"
                rules={[{ required: modalProvider === 'custom_cli', message: '请填写本机 CLI 命令' }]}
              >
                <Input
                  placeholder={DEFAULT_CLI_COMMANDS[modalProvider] || 'my-agent-cli'}
                  onBlur={() => {
                    if (modalProvider && isLocalCliProvider(modalProvider)) {
                      fetchModels()
                    }
                  }}
                />
              </Form.Item>
              <Form.Item
                name="cli_args"
                label="CLI 参数"
                extra="JSON 数组或普通参数字符串。可使用 {prompt} 和 {model} 占位符。"
              >
                <Input.TextArea
                  rows={3}
                  placeholder={DEFAULT_CLI_ARGS[modalProvider] || '["{prompt}"]'}
                  onBlur={() => {
                    if (modalProvider && isLocalCliProvider(modalProvider)) {
                      fetchModels()
                    }
                  }}
                />
              </Form.Item>
              <Button
                type="link"
                size="small"
                icon={<ReloadOutlined spin={testingConnection} />}
                loading={testingConnection}
                onClick={testConnection}
                style={{ padding: 0, marginTop: -8, marginBottom: 12 }}
              >
                测试本机 CLI
              </Button>
            </>
          )}

          <Form.Item
            name="default_model"
            label="默认模型"
            extra={isLocalCliProvider(modalProvider) ? '列表由司命调用本机 CLI 自动获取；仍可直接输入模型名作为兜底。' : undefined}
            rules={[{ required: true, message: '请选择默认模型名' }]}
          >
            {isLocalCliProvider(modalProvider) ? (
              <AutoComplete
                options={defaultModelOptions.map((m) => ({
                  value: m.id,
                  label: m.display_name || m.id,
                }))}
                placeholder="输入 CLI 支持的模型名，或选择候选项"
                filterOption={(input, option) =>
                  String(option?.label || option?.value || '').toLowerCase().includes(input.toLowerCase())
                }
                onChange={(modelName) => {
                  const provider = resolveProviderForSubmit(form.getFieldsValue())
                  form.setFieldsValue(defaultSafetyLimits(provider, modelName))
                }}
              />
            ) : customManualEntry ? (
              <Input
                placeholder="例如 openai/gpt-4o-mini 或 vendor-model-name"
                onChange={(event) => {
                  const provider = resolveProviderForSubmit(form.getFieldsValue())
                  form.setFieldsValue(defaultSafetyLimits(provider, event.target.value))
                }}
              />
            ) : (
              <Select
                showSearch
                loading={modelsLoading}
                disabled={customModelSelection && modelDiscovery.status === 'idle' && defaultModelOptions.length === 0}
                placeholder={
                  modelsLoading
                    ? '正在获取模型列表...'
                    : customModelSelection && modelDiscovery.status === 'idle'
                    ? '填写 API 端点和 API Key 后自动拉取'
                    : defaultModelOptions.length > 0
                    ? '选择模型名'
                    : '请先输入 API Key 以获取模型列表'
                }
                notFoundContent={
                  modelsLoading
                    ? '加载中...'
                    : form.getFieldValue('api_key') || editingProvider
                    ? '未找到模型'
                    : '请先输入 API Key'
                }
                filterOption={(input, option) =>
                  (option?.label as string)?.toLowerCase().includes(input.toLowerCase())
                }
                onChange={(modelName) => {
                  const provider = resolveProviderForSubmit(form.getFieldsValue())
                  form.setFieldsValue(defaultSafetyLimits(provider, modelName))
                }}
                options={defaultModelOptions.map((m) => ({
                  value: m.id,
                  label: m.display_name || m.id,
                }))}
              />
            )}
          </Form.Item>

          <Collapse
            ghost
            size="small"
            items={[{
              key: 'advanced',
              label: '高级设置（输出限制与拆书参数）',
              children: (
                <>
                  <Form.Item
                    name="max_output_tokens"
                    label="模型最大输出 tokens"
                    extra="默认按模型能力上限填充；DeepSeek v4-pro / v4-flash 默认为 384,000，Gemini 默认为 65,536。"
                    rules={[{ required: true, message: '请填写最大输出 tokens' }]}
                  >
                    <InputNumber min={1} max={1000000} style={{ width: '100%' }} />
                  </Form.Item>

                  <Form.Item
                    name="deconstruct_input_char_limit"
                    label="拆书合并输入字符上限"
                    extra="控制每次合并请求最多携带多少分块事实卡片内容。"
                    rules={[{ required: true, message: '请填写合并输入字符上限' }]}
                  >
                    <InputNumber min={1} max={1000000} style={{ width: '100%' }} />
                  </Form.Item>

                  <Form.Item
                    name="deconstruct_item_char_limit"
                    label="拆书单条内容字符上限"
                    extra="控制单条事件、设定、角色字段的最大长度；超过后才会压缩。"
                    rules={[{ required: true, message: '请填写单条内容字符上限' }]}
                  >
                    <InputNumber min={1} max={1000000} style={{ width: '100%' }} />
                  </Form.Item>
                </>
              ),
            }]}
          />

          {!isLocalCliProvider(modalProvider) && (
          <>
          <Button
            type="default"
            icon={<ReloadOutlined spin={testingConnection} />}
            loading={testingConnection}
            onClick={testConnection}
            style={{ marginBottom: 16 }}
          >
            用当前模型真实测试
          </Button>
          {connectionTestResult && (
            <div style={{
              marginTop: -8, marginBottom: 16, fontSize: 13,
              color: connectionTestResult.success ? '#52c41a' : '#ff4d4f',
            }}>
              {connectionTestResult.success
                ? <CheckCircleOutlined />
                : <CloseCircleOutlined />
              }
              {' '}{connectionTestResult.message}
            </div>
          )}
          </>
          )}
        </Form>
      </Modal>
    </div>
  )
}

export default SettingsPage
