import { Button, Collapse, Input, InputNumber, Radio, Space, Typography } from 'antd'

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

function splitLines(value: string) {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)
}

function StructuredValueEditor({ fieldKey, value, onChange }: { fieldKey: string; value: unknown; onChange: (value: unknown) => void }) {
  const label = structuredStageFieldLabel(fieldKey)
  if (typeof value === 'boolean') return <Radio.Group aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}><Radio.Button value>是</Radio.Button><Radio.Button value={false}>否</Radio.Button></Radio.Group>
  if (typeof value === 'number') return <InputNumber aria-label={label} value={value} onChange={(next) => onChange(next ?? 0)} style={{ width: '100%' }} />
  if (typeof value === 'string' || value == null) {
    const text = value == null ? '' : value
    const multiline = text.length > 80 || ['summary', 'content', 'description', 'background', 'story_overview', 'core_conflict', 'ending_direction'].includes(fieldKey)
    return multiline ? <TextArea aria-label={label} value={text} rows={3} onChange={(event) => onChange(event.target.value)} /> : <Input aria-label={label} value={text} onChange={(event) => onChange(event.target.value)} />
  }
  if (Array.isArray(value)) {
    const addItem = () => onChange([...value, blankCollectionItem(fieldKey)])
    if (value.length === 0 && typeof blankCollectionItem(fieldKey) === 'object') return <Button size="small" onClick={addItem}>添加一项</Button>
    const onlySimpleValues = value.every((item) => ['string', 'number', 'boolean'].includes(typeof item))
    if (onlySimpleValues) return <TextArea aria-label={label} value={value.map(String).join('\n')} rows={Math.min(6, Math.max(2, value.length + 1))} placeholder="每行一项" onChange={(event) => onChange(splitLines(event.target.value))} />
    const activeKeys = value.map((_, index) => `${fieldKey}-${index}`)
    return <Space direction="vertical" size={8} style={{ width: '100%' }}><Collapse size="small" className="creation-structured-collection" defaultActiveKey={activeKeys} items={value.map((item, index) => ({ key: `${fieldKey}-${index}`, label: collectionItemLabel(item, index), children: <StructuredValueEditor fieldKey={`${fieldKey}_${index + 1}`} value={item} onChange={(next) => { const updated = [...value]; updated[index] = next; onChange(updated) }} /> }))} /><Button size="small" onClick={addItem}>添加一项</Button></Space>
  }
  if (isRecord(value)) return <div className="creation-structured-fields">{Object.entries(value).map(([key, child]) => <div className="creation-structured-field" key={key}><Text strong>{structuredStageFieldLabel(key)}</Text><StructuredValueEditor fieldKey={key} value={child} onChange={(next) => onChange({ ...value, [key]: next })} /></div>)}</div>
  return <Text type="secondary">暂不支持直接编辑此字段</Text>
}

export function StructuredStageEditor({ data, onChange }: { data: Record<string, unknown>; onChange: (data: Record<string, unknown>) => void }) {
  return <StructuredValueEditor fieldKey="stage" value={data} onChange={(next) => onChange(isRecord(next) ? next : data)} />
}
