import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  type SharedModelConfig,
  useGlobalModelActions,
  useSharedModelConfigs,
} from '../shared/query/modelConfigs'

export type ModelConfig = SharedModelConfig

export interface ModelSelectOption {
  value: string
  label: string
  provider: string
  model: string
  isGlobalDefault: boolean
}

const PROVIDER_LABEL_MAP: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic Claude',
  deepseek: 'DeepSeek',
  qwen: '通义千问',
  gemini: 'Google Gemini',
  claude_cli: 'Claude Code CLI',
  codex_cli: 'Codex CLI',
  opencode_cli: 'opencode CLI',
  mimocode_cli: 'MiMo Code CLI',
  cursor_cli: 'Cursor Agent CLI',
  kilocode_cli: 'Kilo Code CLI',
  qwen_code_cli: 'Qwen Code CLI',
  hermes_cli: 'Hermes Agent CLI',
  openclaw_cli: 'OpenClaw CLI',
  custom_cli: '自定义本机 CLI',
  local_llama_cpp: '司命本地 AI',
}

const modelValue = (provider: string, model: string) => (
  model.includes(':') ? model : `${provider}:${model}`
)

const normalizeModel = (provider: string, model: string) => {
  if (provider === 'deepseek' && model === 'deepseek-v3') {
    return 'deepseek-v4-flash'
  }
  if (provider === 'gemini' && model.startsWith('models/')) {
    return model.slice('models/'.length)
  }
  return model
}

export function useModelOptions() {
  const configsQuery = useSharedModelConfigs()
  const { setGlobalModel: persistGlobalModel } = useGlobalModelActions()
  const configs = useMemo(() => configsQuery.data?.items || [], [configsQuery.data?.items])
  const [selectionOverride, setSelectionOverride] = useState<string>()

  useEffect(() => {
    const handleSelection = (event: Event) => {
      const value = (event as CustomEvent<string>).detail
      if (value) setSelectionOverride(value)
    }
    window.addEventListener('siming:global-model-changed', handleSelection)
    return () => window.removeEventListener('siming:global-model-changed', handleSelection)
  }, [])

  const effectiveConfigs = useMemo(() => {
    if (!selectionOverride) return configs
    const separator = selectionOverride.indexOf(':')
    if (separator <= 0) return configs
    const provider = selectionOverride.slice(0, separator)
    const model = selectionOverride.slice(separator + 1)
    return configs.map((config) => ({
      ...config,
      default_model: config.provider === provider ? model : config.default_model,
      is_global_default: `${config.provider}:${config.default_model}` === selectionOverride
        || config.provider === provider,
    }))
  }, [configs, selectionOverride])

  const modelOptions = useMemo<ModelSelectOption[]>(() => (
    effectiveConfigs.filter((config) => config.is_usable && config.readiness_status === 'ready').map((config) => {
      const model = normalizeModel(config.provider, config.default_model)
      const localRuntimeSuffix = config.provider === 'local_llama_cpp' ? '（本地文本）' : ''
      return {
        value: modelValue(config.provider, model),
        label: `${PROVIDER_LABEL_MAP[config.provider] || config.provider} · ${model}${localRuntimeSuffix}${config.is_global_default ? '（全局默认）' : ''}`,
        provider: config.provider,
        model,
        isGlobalDefault: config.is_global_default,
      }
    })
  ), [effectiveConfigs])

  const defaultModel = useMemo(
    () => modelOptions.find((option) => option.isGlobalDefault)?.value,
    [modelOptions],
  )

  const detectedConfigs = useMemo(
    () => configs.filter((config) => !config.is_usable),
    [configs],
  )

  const setGlobalModel = useCallback(async (value: string) => {
    const option = modelOptions.find((candidate) => candidate.value === value)
    if (!option) throw new Error('所选模型尚未通过真实对话测试')
    await persistGlobalModel(option.provider, option.model)
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('siming:global-model-changed', { detail: value }))
    }
    return option
  }, [modelOptions, persistGlobalModel])

  return {
    configs,
    modelOptions,
    defaultModel,
    loading: configsQuery.isLoading || configsQuery.isFetching,
    refresh: configsQuery.refetch,
    setGlobalModel,
    hasModels: modelOptions.length > 0,
    hasDetectedModels: detectedConfigs.length > 0,
    detectedConfigs,
  }
}
