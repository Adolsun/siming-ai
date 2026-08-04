import {
  Alert,
  Badge,
  Card,
  Collapse,
  Descriptions,
  Divider,
  Empty,
  Space,
  Tag,
  Timeline,
  Typography,
} from 'antd'
import { structuredStageFieldLabel } from '../../components/novel-creation/StructuredStageEditor'

const { Paragraph, Text } = Typography
function fieldLabel(key: string) {
  return structuredStageFieldLabel(key)
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
    return <Collapse className="creation-outline-collapse" defaultActiveKey={chapters.map((chapter) => String(chapter.client_id))} items={chapters.map((chapter) => { const childSections = sections.filter((section) => section.parent_client_id === chapter.client_id); return { key: String(chapter.client_id), label: <Space><Text strong>{String(chapter.title)}</Text><Tag>{childSections.length} 个场景</Tag></Space>, children: <><Paragraph>{String(chapter.summary || '')}</Paragraph>{childSections.map((section, index) => { const metadata = (section.metadata || {}) as Record<string, unknown>; return <div className="creation-section-row" key={`${String(section.client_id)}-${index}`}><Badge count={index + 1} color="var(--ant-color-primary)" /><div><Text strong>{String(section.title)}</Text><Paragraph type="secondary">{String(metadata.purpose || section.summary || '')}</Paragraph><Space wrap size={4}><Tag>{String(metadata.location || '地点待定')}</Tag><Tag>{String(metadata.pov_character || '视角待定')}</Tag><Tag>{String(metadata.exit_state || '状态待定')}</Tag></Space></div></div> })}</> } })} />
  }
  if (stage === 'final_review') {
    const counts = (data.counts || {}) as Record<string, unknown>
    const blocking = Array.isArray(data.blocking) ? data.blocking as string[] : []
    const warnings = Array.isArray(data.warnings) ? data.warnings as string[] : []
    return <div className="creation-final-review"><Alert type={data.ready ? 'success' : 'error'} showIcon message={data.ready ? '立项档案已达到创建标准' : '还不能创建正式作品'} description={blocking.join('；') || '所有关键阶段和颗粒度检查均已通过。'} /><div className="creation-count-grid">{Object.entries(counts).map(([key, value]) => <div key={key}><strong>{String(value)}</strong><span>{({ characters: '角色', worldbuilding: '世界设定', chapters: '细纲章节', sections: '场景事件' } as Record<string, string>)[key] || key}</span></div>)}</div>{warnings.map((warning) => <Alert key={warning} type="warning" showIcon message={warning} />)}</div>
  }
  return <pre className="creation-json-preview">{JSON.stringify(data, null, 2)}</pre>
}
