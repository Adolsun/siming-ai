import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert,
  Button,
  Collapse,
  Drawer,
  Empty,
  Input,
  List,
  Modal,
  Progress,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import {
  EyeOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  SyncOutlined,
} from '@ant-design/icons'
import { ContextInspectorButton } from '../shared/ui/ContextInspectorButton'
import { apiClient } from '../api/client'
import { createLatestRequestGate } from '../shared/latestRequest'

const { Text, Title } = Typography

interface ApiResponse<T> {
  code: number
  message: string
  data: T
}

interface ManifestItem {
  id: string
  category: string
  source_type: string
  source_id?: string | null
  chunk_id?: string | null
  source_hash?: string | null
  title: string
  required: boolean
  pinned: boolean
  estimated_tokens: number
  selection_reason: string
  evidence_submitted_at?: string | null
  scores: { lexical?: number | null; semantic?: number | null; recency?: number | null; structural?: number | null; final?: number | null }
  content?: string
}

interface ContextManifest {
  id: string
  task_type: string
  model?: string | null
  provider?: string | null
  execution_route: string
  status: string
  warnings: string[]
  coverage: Record<string, { required?: boolean; status?: string; item_count?: number; reason?: string }>
  budget: {
    context_window_tokens: number
    input_budget_tokens: number
    output_reserve_tokens: number
    safety_margin_tokens: number
    estimated_input_tokens: number
    estimated_input_chars: number
    remaining_input_tokens: number
  }
  override?: { reason?: string | null; actor?: string | null; at?: string | null }
  stale_reason?: string | null
  items: ManifestItem[]
  created_at?: string | null
}

interface ProjectContextStatus {
  generation_allowed: boolean
  reason?: string
  semantic?: { available?: boolean; model?: string; reason?: string }
}

interface RebuildProject {
  project_id: string
  status: string
  indexed_chunks: number
  semantic_chunks: number
  error?: string | null
}

interface RebuildJob {
  id: string
  status: string
  total_projects: number
  completed_projects: number
  failed_projects: number
  projects: RebuildProject[]
}

const STATUS_COLOR: Record<string, string> = {
  ready: 'green',
  overridden: 'gold',
  needs_confirmation: 'orange',
  stale: 'red',
  blocked_rebuild: 'volcano',
  queued: 'blue',
  running: 'processing',
  completed: 'green',
  failed: 'red',
}

const STATUS_LABEL: Record<string, string> = {
  ready: '资料已就绪',
  overridden: '作者已确认继续',
  needs_confirmation: '待确认',
  stale: '已失效',
  blocked_rebuild: '索引维护中',
  queued: '排队中',
  running: '重建中',
  completed: '已完成',
  failed: '失败',
}

const TASK_LABEL: Record<string, string> = {
  writing: '章节写作', editing: '正文修改', review: '内容审阅', outline_planning: '大纲规划',
  cataloging: '作品建档', rewrite: '正文改写', new_project: '新书立项', planning: '创作规划',
}
const SOURCE_LABEL: Record<string, string> = {
  target_outline: '本次大纲', target_chapter: '本章正文', target_text: '待处理正文',
  style: '写作风格', previous_summary: '前文摘要', scene_character: '相关角色',
  worldbuilding: '世界观', narrative_governance: '叙事约束', user_requirement: '作者要求',
  outline_position: '大纲位置', outline_parent: '上级大纲', memory: '创作记忆', skill: '写作技能',
  hybrid_retrieval: '检索到的资料', confirmed_fact: '已确认事实', adjacent_summary: '相邻章节摘要',
  creation_session: '立项资料', confirmed_stage: '已确认阶段', author_constraint: '作者约束',
}
const COVERAGE_LABEL: Record<string, string> = {
  covered: '已具备', missing: '缺少资料', not_applicable: '本次无需', unknown: '尚未确认',
}

const tokenPercent = (manifest: ContextManifest) => {
  const total = Math.max(1, manifest.budget.input_budget_tokens)
  return Math.min(100, Math.round((manifest.budget.estimated_input_tokens / total) * 100))
}

export default function ContextGovernancePage({ projectId }: { projectId: string }) {
  const [manifests, setManifests] = useState<ContextManifest[]>([])
  const [status, setStatus] = useState<ProjectContextStatus | null>(null)
  const [rebuild, setRebuild] = useState<RebuildJob | null>(null)
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState<ContextManifest | null>(null)
  const [overrideTarget, setOverrideTarget] = useState<ContextManifest | null>(null)
  const [overrideReason, setOverrideReason] = useState('')
  const [submittingOverride, setSubmittingOverride] = useState(false)
  const manifestRequestGate = useRef(createLatestRequestGate<string>())
  const selectedManifestIdRef = useRef<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [statusResponse, manifestsResponse, rebuildResponse] = await Promise.all([
        apiClient.get<ApiResponse<ProjectContextStatus>>(`/projects/${projectId}/context-governance-status`),
        apiClient.get<ApiResponse<{ items: ContextManifest[] }>>(`/projects/${projectId}/context-manifests`),
        apiClient.get<ApiResponse<{ items: RebuildJob[] }>>('/context-governance/rebuilds', { limit: 12 }),
      ])
      setStatus(statusResponse.data.data)
      setManifests(manifestsResponse.data.data.items || [])
      const relevant = (rebuildResponse.data.data.items || []).find((job) => job.projects.some((item) => item.project_id === projectId)) || null
      setRebuild(relevant)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载上下文治理状态失败')
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    const manifestGate = manifestRequestGate.current
    manifestGate.invalidate()
    selectedManifestIdRef.current = null
    setSelected(null)
    void load()
    return () => manifestGate.invalidate()
  }, [load])

  const openManifest = async (manifest: ContextManifest) => {
    const request = manifestRequestGate.current.begin(manifest.id)
    selectedManifestIdRef.current = manifest.id
    setSelected(null)
    try {
      const response = await apiClient.get<ApiResponse<ContextManifest>>(`/projects/${projectId}/context-manifests/${manifest.id}`)
      if (
        manifestRequestGate.current.isCurrent(request)
        && selectedManifestIdRef.current === manifest.id
        && response.data.data.id === manifest.id
      ) {
        setSelected(response.data.data)
      }
    } catch (error) {
      if (manifestRequestGate.current.isCurrent(request) && selectedManifestIdRef.current === manifest.id) {
        message.error(error instanceof Error ? error.message : '加载 Manifest 失败')
      }
    }
  }

  const closeManifest = () => {
    manifestRequestGate.current.invalidate()
    selectedManifestIdRef.current = null
    setSelected(null)
  }

  const rebuildProject = async () => {
    try {
      await apiClient.post('/context-governance/rebuilds', { project_ids: [projectId], requested_by: 'author' })
      message.success('上下文索引重建已开始')
      load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '无法启动索引重建')
    }
  }

  const submitOverride = async () => {
    if (!overrideTarget || !overrideReason.trim()) return
    setSubmittingOverride(true)
    try {
      await apiClient.post(`/projects/${projectId}/context-manifests/${overrideTarget.id}/override`, {
        reason: overrideReason.trim(),
        actor: 'author',
      })
      message.success('已记录继续执行的原因')
      setOverrideTarget(null)
      setOverrideReason('')
      load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '确认原因未保存')
    } finally {
      setSubmittingOverride(false)
    }
  }

  const currentRebuild = useMemo(
    () => rebuild?.projects.find((item) => item.project_id === projectId) || null,
    [projectId, rebuild],
  )

  const columns = [
    {
      title: '状态',
      dataIndex: 'status',
      width: 118,
      render: (value: string) => <Tag color={STATUS_COLOR[value] || 'default'}>{STATUS_LABEL[value] || value}</Tag>,
    },
    {
      title: '任务',
      dataIndex: 'task_type',
      width: 126,
      render: (value: string) => <Text strong>{TASK_LABEL[value] || value}</Text>,
    },
    {
      title: '预计资料占用',
      key: 'budget',
      width: 220,
      render: (_: unknown, item: ContextManifest) => (
        <div style={{ minWidth: 170 }}>
          <Progress percent={tokenPercent(item)} size="small" status={item.status === 'stale' ? 'exception' : undefined} showInfo={false} />
          <Text type="secondary" style={{ fontSize: 11 }}>约 {item.budget.estimated_input_tokens} / {item.budget.input_budget_tokens} tokens</Text>
        </div>
      ),
    },
    {
      title: '模型',
      key: 'model',
      render: (_: unknown, item: ContextManifest) => (
        <Text
          ellipsis={{ tooltip: item.model || '这条清单未记录模型名称；容量估算请查看本次资料详情。' }}
          style={{ maxWidth: 180 }}
        >
          {item.model || '未记录模型名称'}
        </Text>
      ),
    },
    {
      title: '操作',
      width: 120,
      render: (_: unknown, item: ContextManifest) => (
        <Space size={2}>
          <Button type="text" icon={<EyeOutlined />} onClick={() => openManifest(item)}>查看资料</Button>
          {item.status === 'needs_confirmation' && <Button type="text" icon={<SafetyCertificateOutlined />} title="说明资料不足时仍要继续的原因" onClick={() => setOverrideTarget(item)} />}
        </Space>
      ),
    },
  ]

  return (
    <div style={{ maxWidth: 1500, margin: '0 auto' }}>
      <Space wrap align="start" style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>AI 参考资料</Title>
          <Text type="secondary">查看写作任务准备参考哪些作品资料、是否有缺失，以及预计占用多少上下文容量。</Text>
        </div>
        <Space>
          <ContextInspectorButton scope={{ kind: 'project_conversation', id: projectId }} label="查看调用记录" />
          <Button icon={<ReloadOutlined />} loading={loading} onClick={load}>刷新</Button>
        </Space>
      </Space>

      <Alert type="info" showIcon style={{ marginBottom: 16 }} message="这里展示写作前准备的资料清单。"
        description="想看实际发给模型的提示词、对话、工具调用和返回内容，请点击“查看调用记录”。开启调用记录也可以从主界面的“调用记录”入口完成，无需先创建作品。" />

      {status && !status.generation_allowed && (
        <Alert
          type="warning"
          showIcon
          message="该作品的生成与正式写入暂时受限"
          description={status.reason || '上下文索引尚未达到当前版本。浏览、编辑与检索仍可使用。'}
          style={{ marginBottom: 16 }}
        />
      )}

      {currentRebuild && currentRebuild.status !== 'completed' && (
        <Alert
          type={currentRebuild.status === 'failed' ? 'error' : 'info'}
          showIcon
          message={`索引${STATUS_LABEL[currentRebuild.status] || currentRebuild.status}`}
          description={`已整理 ${currentRebuild.indexed_chunks} 个资料片段，其中 ${currentRebuild.semantic_chunks} 个支持按含义检索${currentRebuild.error ? `。${currentRebuild.error}` : ''}`}
          style={{ marginBottom: 16 }}
        />
      )}

      <Table
        rowKey="id"
        loading={loading}
        size="small"
        dataSource={manifests}
        columns={columns}
        pagination={{ pageSize: 12, hideOnSinglePage: true }}
        locale={{ emptyText: <Empty description="还没有写作参考资料清单。写作任务准备资料后会显示在这里；立项对话请到“调用记录”查看。" /> }}
        scroll={{ x: 820 }}
      />

      <Collapse style={{ marginTop: 16 }} items={[{ key: 'maintenance', label: '资料检索与维护', children: <Space direction="vertical">
        <Text type="secondary">资料索引用于从作品中找到相关片段。更新资料后检索结果异常时，可以重新整理；这不会改写作品正文。</Text>
        {status?.semantic && <><Tag color={status.semantic.available ? 'green' : 'default'}>{status.semantic.available ? '支持按内容含义检索' : '使用关键词检索'}</Tag>
          <Text type="secondary">{status.semantic.model}{status.semantic.reason ? ` · ${status.semantic.reason}` : ''}</Text></>}
        <Button icon={<SyncOutlined />} loading={loading} onClick={rebuildProject}>重新整理资料索引</Button>
      </Space> }]} />

      <Drawer
        title={selected ? `参考资料 · ${TASK_LABEL[selected.task_type] || selected.task_type}` : '参考资料'}
        open={Boolean(selected)}
        onClose={closeManifest}
        width={Math.min(760, window.innerWidth - 36)}
      >
        {selected && (
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Alert
              type={selected.status === 'ready' || selected.status === 'overridden' ? 'success' : 'warning'}
              showIcon
              message={STATUS_LABEL[selected.status] || selected.status}
              description={selected.stale_reason || selected.override?.reason || selected.warnings?.[0] || '下面保留本次任务准备引用的资料及选择原因。'}
            />
            <div>
              <Text strong>预计资料占用</Text>
              <Progress percent={tokenPercent(selected)} status={selected.status === 'stale' ? 'exception' : undefined} />
              <Text type="secondary">约 {selected.budget.estimated_input_tokens} / {selected.budget.input_budget_tokens} tokens。token 是模型计算文本长度的单位，这里的估算不代表实际消耗。</Text>
              <details><summary>容量计算详情</summary><Text type="secondary">为回答预留 {selected.budget.output_reserve_tokens}，安全余量 {selected.budget.safety_margin_tokens}。执行方式：{selected.execution_route}</Text></details>
            </div>
            <div>
              <Text strong>需要的资料是否齐全</Text>
              <List
                size="small"
                dataSource={Object.entries(selected.coverage || {})}
                renderItem={([name, item]) => (
                  <List.Item>
                    <Space direction="vertical" size={0} style={{ width: '100%' }}>
                      <Space><Tag color={item.status === 'covered' || item.status === 'not_applicable' ? 'green' : 'orange'}>{COVERAGE_LABEL[item.status || 'unknown'] || item.status}</Tag><Text>{SOURCE_LABEL[name] || name}</Text>{item.required && <Tag>必需</Tag>}</Space>
                      {item.reason && <Text type="secondary" style={{ fontSize: 12 }}>{item.reason}</Text>}
                    </Space>
                  </List.Item>
                )}
              />
            </div>
            <div>
              <Text strong>选中的参考资料</Text>
              <List
                size="small"
                dataSource={selected.items || []}
                renderItem={(item) => (
                  <List.Item>
                    <Space direction="vertical" size={3} style={{ width: '100%' }}>
                      <Space wrap><Tag>{SOURCE_LABEL[item.category] || item.category}</Tag>{item.required && <Tag color="red">必需</Tag>}{item.pinned && <Tag color="gold">固定</Tag>}<Text strong>{item.title}</Text></Space>
                      <Text type="secondary" style={{ fontSize: 12 }}>预计约 {item.estimated_tokens} tokens</Text>
                      <Text style={{ fontSize: 12 }}>{item.selection_reason}</Text>
                      <details><summary>来源标识与校验值</summary><Text type="secondary">{item.source_type}:{item.source_id || item.chunk_id || 'inline'}<br />hash: {item.source_hash || 'n/a'}</Text></details>
                    </Space>
                  </List.Item>
                )}
              />
            </div>
          </Space>
        )}
      </Drawer>

      <Modal
        title="资料不足时仍要继续"
        open={Boolean(overrideTarget)}
        okText="确认允许继续"
        okButtonProps={{ disabled: !overrideReason.trim(), loading: submittingOverride }}
        onOk={submitOverride}
        onCancel={() => { setOverrideTarget(null); setOverrideReason('') }}
      >
        <Text type="secondary">请说明缺少这些资料仍可继续的原因。系统会保存你的确认；之后资料发生变化时仍会重新检查。</Text>
        <Input.TextArea
          autoFocus
          rows={4}
          value={overrideReason}
          onChange={(event) => setOverrideReason(event.target.value)}
          placeholder="说明为何可以在缺少该上下文时继续"
          style={{ marginTop: 12 }}
        />
      </Modal>
    </div>
  )
}
