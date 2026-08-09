import { DeleteOutlined, LockOutlined, PlusOutlined } from '@ant-design/icons'
import { Button, Collapse, Empty, Input, InputNumber, Popconfirm, Radio, Select, Space, Tag, Tooltip, Typography } from 'antd'
import './StructuredStageEditor.css'

const { Text } = Typography
const { TextArea } = Input

const stageFieldLabels: Record<string, string> = {
  brief: '创作构想', preset_id: '创作模式', theme_id: '题材方向', genre: '作品类型',
  target_audience: '目标读者', platform: '发布平台', target_words: '目标字数', opening_chapters: '开篇细纲章数',
  special_requirements: '特别要求', avoid: '需要避开的内容', selected_concept_id: '当前创意', options: '创意方案',
  writing_style: '正文风格', world_tone: '世界基调', story_structure: '剧情结构', pacing: '叙事节奏',
  style_rules: '文风规则', forbidden_patterns: '避雷项', worldbuilding: '世界设定', display_groups: '展示分组',
  characters: '角色', relationships: '角色关系', entries: '地点与势力', relations: '稳定关系',
  story_overview: '故事总览', core_conflict: '核心冲突', ending_direction: '结局方向', target_chapters: '目标章节数',
  volumes: '分卷规划', stage_plan: '阶段规划', chapters: '章节细纲', sections: '场景事件',
  title: '标题', name: '名称', summary: '摘要', content: '内容', description: '说明', dimension: '维度',
  role_type: '角色类型', background: '背景', personality: '性格', goal: '目标', current_goal: '当前目标', profile: '写作锁',
  source_title: '起点', target_title: '终点', relation_type: '关系类型', start_chapter: '起始章节', end_chapter: '结束章节',
  client_id: '内部标识', parent_client_id: '所属章节', metadata: '场景信息', ready: '可以创建', blocking: '阻塞项', warnings: '提醒', counts: '数量检查',
  core_tone: '核心基调', atmosphere: '氛围', emotional_color: '情绪色彩', reader_experience: '读者感受',
  narrative_perspective: '叙事视角', perspective: '叙事视角', sentence_rhythm: '句式节奏', language_style: '语言风格',
  main_line: '主线结构', stages: '阶段安排', opening: '开篇节奏', middle: '中段节奏', climax: '高潮节奏',
}

const hiddenTechnicalFields = new Set([
  'client_id',
  'node_type',
  'opening_chapter_count',
  'section_rule',
  'display_groups',
  'stage_plan',
])

const computedFields = new Set(['ready', 'blocking', 'warnings', 'counts'])

export function structuredStageFieldLabel(key: string) {
  return stageFieldLabels[key] || key.replace(/_/g, ' ')
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function collectionItemLabel(value: unknown, index: number) {
  if (!isRecord(value)) return `第 ${index + 1} 项`
  return String(value.title || value.name || value.client_id || value.source_title || `第 ${index + 1} 项`)
}

function generatedClientId(prefix: string) {
  const random = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID().slice(0, 8)
    : Math.random().toString(36).slice(2, 10)
  return `${prefix}-${Date.now().toString(36)}-${random}`
}

function blankCollectionItem(fieldKey: string, rootData: Record<string, unknown>): Record<string, unknown> | string {
  if (fieldKey === 'characters') return { name: '', role_type: 'supporting', background: '', goal: '' }
  if (fieldKey === 'relationships') return { source: '', target: '', relation_type: '', description: '' }
  if (fieldKey === 'worldbuilding') return { title: '', dimension: 'culture', content: '' }
  if (fieldKey === 'entries') return { title: '', description: '' }
  if (fieldKey === 'relations') return { source_title: '', target_title: '', relation_type: '', description: '' }
  if (fieldKey === 'volumes') return { title: '', summary: '', start_chapter: 1, end_chapter: 1 }
  if (fieldKey === 'chapters') return { client_id: generatedClientId('chapter'), node_type: 'chapter', title: '', summary: '' }
  if (fieldKey === 'sections') {
    const firstChapter = Array.isArray(rootData.chapters) ? rootData.chapters.find(isRecord) : undefined
    return {
      client_id: generatedClientId('section'),
      parent_client_id: firstChapter?.client_id || '',
      node_type: 'section',
      title: '',
      summary: '',
    }
  }
  return ''
}

function splitLines(value: string) {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)
}

function readOnlyValue(value: unknown) {
  if (typeof value === 'boolean') return <Tag color={value ? 'success' : 'warning'}>{value ? '是' : '否'}</Tag>
  if (Array.isArray(value)) return value.length ? <ul className="creation-structured-readonly-list">{value.map((item, index) => <li key={`${String(item)}-${index}`}>{String(item)}</li>)}</ul> : <Text type="secondary">无</Text>
  if (isRecord(value)) return <Text type="secondary">{Object.entries(value).map(([key, item]) => `${structuredStageFieldLabel(key)} ${String(item)}`).join(' · ') || '无'}</Text>
  return <Text>{String(value ?? '无')}</Text>
}

interface StructuredValueEditorProps {
  fieldKey: string
  value: unknown
  rootData: Record<string, unknown>
  onChange: (value: unknown) => void
}

function StructuredValueEditor({ fieldKey, value, rootData, onChange }: StructuredValueEditorProps) {
  const label = structuredStageFieldLabel(fieldKey)
  if (computedFields.has(fieldKey)) return <div className="creation-structured-readonly"><LockOutlined />{readOnlyValue(value)}</div>
  if (fieldKey === 'parent_client_id') {
    const chapters = Array.isArray(rootData.chapters) ? rootData.chapters.filter(isRecord) : []
    return (
      <Select
        aria-label={label}
        value={typeof value === 'string' && value ? value : undefined}
        placeholder="选择所属章节"
        options={chapters.map((chapter, index) => ({
          value: String(chapter.client_id || ''),
          label: String(chapter.title || `第 ${index + 1} 章`),
        })).filter((option) => option.value)}
        onChange={onChange}
        style={{ width: '100%' }}
      />
    )
  }
  if (typeof value === 'boolean') return <Radio.Group aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}><Radio.Button value>是</Radio.Button><Radio.Button value={false}>否</Radio.Button></Radio.Group>
  if (typeof value === 'number') return <InputNumber aria-label={label} value={value} onChange={(next) => onChange(next ?? 0)} style={{ width: '100%' }} />
  if (typeof value === 'string' || value == null) {
    const text = value == null ? '' : value
    const multiline = text.length > 80 || ['summary', 'content', 'description', 'background', 'story_overview', 'core_conflict', 'ending_direction'].includes(fieldKey)
    return multiline ? <TextArea aria-label={label} value={text} autoSize={{ minRows: 3, maxRows: 10 }} onChange={(event) => onChange(event.target.value)} /> : <Input aria-label={label} value={text} onChange={(event) => onChange(event.target.value)} />
  }
  if (Array.isArray(value)) {
    const blankItem = blankCollectionItem(fieldKey, rootData)
    const addItem = () => onChange([...value, blankItem])
    const expectsStructuredItems = isRecord(blankItem) || value.some(isRecord)
    const onlySimpleValues = !expectsStructuredItems && value.every((item) => ['string', 'number', 'boolean'].includes(typeof item))
    if (onlySimpleValues) return <TextArea aria-label={label} value={value.map(String).join('\n')} autoSize={{ minRows: 2, maxRows: 8 }} placeholder="每行一项" onChange={(event) => onChange(splitLines(event.target.value))} />
    if (value.length === 0) {
      return (
        <div className="creation-structured-empty">
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={`还没有${label}`} />
          <Button icon={<PlusOutlined />} onClick={addItem}>添加第一项</Button>
        </div>
      )
    }
    return (
      <Space direction="vertical" size={10} className="creation-structured-collection-wrap">
        <div className="creation-structured-collection-toolbar">
          <Text type="secondary">共 {value.length} 项，点击标题展开编辑</Text>
          <Button size="small" icon={<PlusOutlined />} onClick={addItem}>添加一项</Button>
        </div>
        <Collapse
          size="small"
          className="creation-structured-collection"
          items={value.map((item, index) => ({
            key: `${fieldKey}-${index}`,
            label: <span className="creation-structured-collection-label"><span>{collectionItemLabel(item, index)}</span><Tag>{index + 1}/{value.length}</Tag></span>,
            children: (
              <div className="creation-structured-collection-item">
                <div className="creation-structured-collection-actions">
                  <Tooltip title="删除后会在保存时写入，取消编辑可放弃本次修改">
                    <Popconfirm
                      title={`删除“${collectionItemLabel(item, index)}”？`}
                      description="保存修改后，此项会从立项数据中移除。"
                      okText="删除"
                      cancelText="取消"
                      onConfirm={() => onChange(value.filter((_, itemIndex) => itemIndex !== index))}
                    >
                      <Button size="small" danger icon={<DeleteOutlined />}>删除此项</Button>
                    </Popconfirm>
                  </Tooltip>
                </div>
                <StructuredValueEditor
                  fieldKey={`${fieldKey}_${index + 1}`}
                  value={item}
                  rootData={rootData}
                  onChange={(next) => {
                    const updated = [...value]
                    updated[index] = next
                    onChange(updated)
                  }}
                />
              </div>
            ),
          }))}
        />
      </Space>
    )
  }
  if (isRecord(value)) {
    const entries = Object.entries(value).filter(([key]) => !hiddenTechnicalFields.has(key))
    return (
      <div className="creation-structured-fields">
        {entries.map(([key, child]) => (
          <div className={`creation-structured-field${computedFields.has(key) ? ' is-readonly' : ''}`} key={key}>
            <Text strong>{structuredStageFieldLabel(key)}</Text>
            <StructuredValueEditor fieldKey={key} value={child} rootData={rootData} onChange={(next) => onChange({ ...value, [key]: next })} />
          </div>
        ))}
      </div>
    )
  }
  return <Text type="secondary">暂不支持直接编辑此字段</Text>
}

export function StructuredStageEditor({ data, onChange }: { data: Record<string, unknown>; onChange: (data: Record<string, unknown>) => void }) {
  return (
    <div className="creation-structured-stage-editor">
      <StructuredValueEditor fieldKey="stage" value={data} rootData={data} onChange={(next) => onChange(isRecord(next) ? next : data)} />
    </div>
  )
}
