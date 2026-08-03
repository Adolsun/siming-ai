import {
  Alert,
  Badge,
  Button,
  Card,
  Collapse,
  Descriptions,
  Divider,
  Empty,
  Input,
  InputNumber,
  Radio,
  Space,
  Tag,
  Timeline,
  Typography,
} from 'antd'
import { splitLines } from './types'

const { Paragraph, Text } = Typography
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

function fieldLabel(key: string) {
  return stageFieldLabels[key] || key.replace(/_/g, ' ')
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function recordRows(value: unknown, nameField = 'title'): Array<Record<string, unknown>> {
  if (Array.isArray(value)) return value.filter(isRecord)
  if (!isRecord(value)) return []
  return Object.entries(value).flatMap(([name, child]) => {
    if (!isRecord(child)) return []
    return [{ ...child, [nameField]: child[nameField] || name }]
  })
}

function uniqueRows(rows: Array<Record<string, unknown>>, keyBuilder: (item: Record<string, unknown>) => string) {
  const seen = new Set<string>()
  return rows.filter((item) => {
    const key = keyBuilder(item)
    if (!key || !seen.has(key)) {
      if (key) seen.add(key)
      return true
    }
    return false
  })
}

function roleTypeLabel(value: unknown, index: number) {
  const role = String(value || (index === 0 ? 'protagonist' : 'supporting'))
  return ({ protagonist: '主角', supporting: '配角', antagonist: '对手' } as Record<string, string>)[role] || role
}

function volumeRange(item: Record<string, unknown>) {
  if (item.start_chapter && item.end_chapter) return `${String(item.start_chapter)} - ${String(item.end_chapter)} 章`
  const numbers = String(item.chapters || '').match(/\d+/g)
  if (numbers && numbers.length >= 2) return `${numbers[0]} - ${numbers[1]} 章`
  return '章节范围待确认'
}

function collectionItemLabel(value: unknown, index: number) {
  if (!isRecord(value)) return `第 ${index + 1} 项`
  return String(value.title || value.name || value.client_id || value.source_title || `第 ${index + 1} 项`)
}

function blankCollectionItem(fieldKey: string): Record<string, unknown> | string {
  if (fieldKey === 'characters') return { name: '', role_type: 'supporting', background: '', goal: '' }
  if (fieldKey === 'relationships') return { source: '', target: '', relation_type: '', description: '' }
  if (fieldKey === 'worldbuilding') return { title: '', dimension: 'culture', content: '' }
  if (fieldKey === 'entries') return { title: '', description: '' }
  if (fieldKey === 'relations') return { source_title: '', target_title: '', relation_type: '', description: '' }
  if (fieldKey === 'volumes') return { title: '', summary: '', start_chapter: 1, end_chapter: 1 }
  if (fieldKey === 'chapters') return { client_id: '', title: '', summary: '' }
  if (fieldKey === 'sections') return { client_id: '', parent_client_id: '', title: '', summary: '' }
  return ''
}

function StructuredPreviewValue({ value }: { value: unknown }) {
  if (value == null || value === '') return <Text type="secondary">未提供</Text>
  if (typeof value === 'boolean') return <span className="creation-preview-value">{value ? '是' : '否'}</span>
  if (typeof value === 'string' || typeof value === 'number') return <span className="creation-preview-value">{String(value)}</span>
  if (Array.isArray(value)) {
    if (value.length === 0) return <Text type="secondary">未提供</Text>
    return <ul className="creation-preview-list">{value.map((item, index) => <li key={`${collectionItemLabel(item, index)}-${index}`}><StructuredPreviewValue value={item} /></li>)}</ul>
  }
  if (isRecord(value)) {
    const entries = Object.entries(value)
    if (entries.length === 0) return <Text type="secondary">未提供</Text>
    return <dl className="creation-preview-fields">{entries.map(([key, child]) => <div className="creation-preview-field" key={key}><dt>{fieldLabel(key)}</dt><dd><StructuredPreviewValue value={child} /></dd></div>)}</dl>
  }
  return <span className="creation-preview-value">{String(value)}</span>
}

function StructuredValueEditor({ fieldKey, value, onChange }: { fieldKey: string; value: unknown; onChange: (value: unknown) => void }) {
  const label = fieldLabel(fieldKey)
  if (typeof value === 'boolean') return <Radio.Group aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}><Radio.Button value>是</Radio.Button><Radio.Button value={false}>否</Radio.Button></Radio.Group>
  if (typeof value === 'number') return <InputNumber aria-label={label} value={value} onChange={(next) => onChange(next ?? 0)} style={{ width: '100%' }} />
  if (typeof value === 'string' || value == null) {
    const text = value == null ? '' : value
    const multiline = text.length > 80 || ['summary', 'content', 'description', 'background', 'story_overview', 'core_conflict', 'ending_direction'].includes(fieldKey)
    return multiline ? <TextArea aria-label={label} value={text} rows={3} onChange={(event) => onChange(event.target.value)} /> : <Input aria-label={label} value={text} onChange={(event) => onChange(event.target.value)} />
  }
  if (Array.isArray(value)) {
    const addItem = () => onChange([...value, blankCollectionItem(fieldKey)])
    if (value.length === 0 && typeof blankCollectionItem(fieldKey) === 'object') {
      return <Button size="small" onClick={addItem}>添加一项</Button>
    }
    const onlySimpleValues = value.every((item) => ['string', 'number', 'boolean'].includes(typeof item))
    if (onlySimpleValues) return <TextArea aria-label={label} value={value.map(String).join('\n')} rows={Math.min(6, Math.max(2, value.length + 1))} placeholder="每行一项" onChange={(event) => onChange(splitLines(event.target.value))} />
    return <Space direction="vertical" size={8} style={{ width: '100%' }}><Collapse size="small" className="creation-structured-collection" items={value.map((item, index) => ({ key: `${fieldKey}-${index}`, label: collectionItemLabel(item, index), children: <StructuredValueEditor fieldKey={`${fieldKey}_${index + 1}`} value={item} onChange={(next) => { const updated = [...value]; updated[index] = next; onChange(updated) }} /> }))} /><Button size="small" onClick={addItem}>添加一项</Button></Space>
  }
  if (isRecord(value)) {
    return <div className="creation-structured-fields">{Object.entries(value).map(([key, child]) => <div className="creation-structured-field" key={key}><Text strong>{fieldLabel(key)}</Text><StructuredValueEditor fieldKey={key} value={child} onChange={(next) => onChange({ ...value, [key]: next })} /></div>)}</div>
  }
  return <Text type="secondary">暂不支持直接编辑此字段</Text>
}

export function StructuredStageEditor({ data, onChange }: { data: Record<string, unknown>; onChange: (data: Record<string, unknown>) => void }) {
  return <StructuredValueEditor fieldKey="stage" value={data} onChange={(next) => onChange(isRecord(next) ? next : data)} />
}

export function StagePreview({ stage, data }: { stage: string; data?: Record<string, unknown> | null }) {
  if (!data) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="本阶段尚未生成" />
  if (stage === 'world_style') {
    const world = recordRows(data.worldbuilding)
    return <div className="creation-stage-preview"><Descriptions column={{ xs: 1, sm: 1, md: 2, lg: 2, xl: 2, xxl: 2 }} size="small" bordered><Descriptions.Item label="世界基调"><StructuredPreviewValue value={data.world_tone} /></Descriptions.Item><Descriptions.Item label="正文风格"><StructuredPreviewValue value={data.writing_style} /></Descriptions.Item><Descriptions.Item label="结构"><StructuredPreviewValue value={data.story_structure} /></Descriptions.Item><Descriptions.Item label="节奏"><StructuredPreviewValue value={data.pacing} /></Descriptions.Item></Descriptions><div className="creation-item-grid">{world.map((item, index) => <Card key={`${String(item.title)}-${index}`} size="small" title={String(item.title || `设定 ${index + 1}`)} extra={<Tag>{String(item.dimension || 'culture')}</Tag>}><div className="creation-worldbuilding-content"><StructuredPreviewValue value={item.content || item.description} /></div></Card>)}</div></div>
  }
  if (stage === 'characters') {
    const characters = recordRows(data.characters, 'name')
    return <div className="creation-item-grid creation-character-grid">{characters.map((item, index) => { const profile = (item.profile || {}) as Record<string, unknown>; return <Card key={`${String(item.name)}-${index}`} size="small" title={String(item.name || `角色 ${index + 1}`)} extra={<Tag>{roleTypeLabel(item.role_type, index)}</Tag>}><Paragraph>{String(item.background || item.personality || '')}</Paragraph><Descriptions column={1} size="small"><Descriptions.Item label="当前目标">{String(item.goal || item.current_goal || profile.core_motivation || '待补充')}</Descriptions.Item><Descriptions.Item label="核心动机">{String(profile.core_motivation || '')}</Descriptions.Item><Descriptions.Item label="内在缺口">{String(profile.inner_lack || '')}</Descriptions.Item><Descriptions.Item label="声线">{String(profile.voice || '')}</Descriptions.Item></Descriptions></Card> })}</div>
  }
  if (stage === 'locations') {
    const entries = uniqueRows(recordRows(data.entries), (item) => String(item.title || '').trim().toLocaleLowerCase())
    const relations = uniqueRows(recordRows(data.relations), (item) => [item.source_title, item.target_title, item.relation_type].map((value) => String(value || '').trim().toLocaleLowerCase()).join('|'))
    return <div className="creation-stage-preview"><div className="creation-item-grid">{entries.map((item, index) => <Card size="small" key={`${String(item.title)}-${index}`} title={String(item.title || `地点 ${index + 1}`)}><Paragraph>{String(item.content || item.description || '')}</Paragraph></Card>)}</div><Divider orientation="left">稳定关系</Divider><Timeline items={relations.map((item) => ({ children: <><Text strong>{String(item.source_title)}</Text> <Text type="secondary">{String(item.relation_type)}</Text> <Text strong>{String(item.target_title)}</Text><br /><Text type="secondary">{String(item.description || '')}</Text></> }))} /></div>
  }
  if (stage === 'macro_outline') {
    const volumes = recordRows(data.volumes)
    return <div className="creation-stage-preview"><Alert type="info" showIcon message={String(data.core_conflict || '')} description={String(data.story_overview || '')} /><Timeline className="creation-volume-timeline" items={volumes.map((item) => ({ children: <div><Text strong>{String(item.title || '')}</Text><Tag style={{ marginLeft: 8 }}>{volumeRange(item)}</Tag><Paragraph>{String(item.summary || item.core_function || item.focus || '')}</Paragraph></div> }))} /></div>
  }
  if (stage === 'opening_outline') {
    const chapters = Array.isArray(data.chapters) ? data.chapters as Array<Record<string, unknown>> : []
    const sections = Array.isArray(data.sections) ? data.sections as Array<Record<string, unknown>> : []
    return <Collapse className="creation-outline-collapse" items={chapters.map((chapter) => { const childSections = sections.filter((section) => section.parent_client_id === chapter.client_id); return { key: String(chapter.client_id), label: <Space><Text strong>{String(chapter.title)}</Text><Tag>{childSections.length} 个场景</Tag></Space>, children: <><Paragraph>{String(chapter.summary || '')}</Paragraph>{childSections.map((section, index) => { const metadata = (section.metadata || {}) as Record<string, unknown>; return <div className="creation-section-row" key={`${String(section.client_id)}-${index}`}><Badge count={index + 1} color="var(--ant-color-primary)" /><div><Text strong>{String(section.title)}</Text><Paragraph type="secondary">{String(metadata.purpose || section.summary || '')}</Paragraph><Space wrap size={4}><Tag>{String(metadata.location || '地点待定')}</Tag><Tag>{String(metadata.pov_character || '视角待定')}</Tag><Tag>{String(metadata.exit_state || '状态待定')}</Tag></Space></div></div> })}</> } })} />
  }
  if (stage === 'final_review') {
    const counts = (data.counts || {}) as Record<string, unknown>
    const blocking = Array.isArray(data.blocking) ? data.blocking as string[] : []
    const warnings = Array.isArray(data.warnings) ? data.warnings as string[] : []
    return <div className="creation-final-review"><Alert type={data.ready ? 'success' : 'error'} showIcon message={data.ready ? '立项档案已达到创建标准' : '还不能创建正式作品'} description={blocking.join('；') || '所有关键阶段和颗粒度检查均已通过。'} /><div className="creation-count-grid">{Object.entries(counts).map(([key, value]) => <div key={key}><strong>{String(value)}</strong><span>{({ characters: '角色', worldbuilding: '世界设定', chapters: '细纲章节', sections: '场景事件' } as Record<string, string>)[key] || key}</span></div>)}</div>{warnings.map((warning) => <Alert key={warning} type="warning" showIcon message={warning} />)}</div>
  }
  return <pre className="creation-json-preview">{JSON.stringify(data, null, 2)}</pre>
}
