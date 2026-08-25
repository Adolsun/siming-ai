import { useCallback, useRef, useState } from 'react'
import {
  Alert,
  Badge,
  Button,
  Card,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Space,
  Spin,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd'
import {
  BulbOutlined,
  CompassOutlined,
  DatabaseOutlined,
  FontSizeOutlined,
  ReloadOutlined,
  RobotOutlined,
  SaveOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'
import { useAiPanelContext } from '../contexts/AiPanelContext'
import {
  ensureCreationBrief,
  fetchCreationBrief,
  updateCreationBrief,
  type CreationContext,
  type CreationSessionSummary,
} from '../features/creationBrief/api'
import { useCreationBriefLifecycle } from '../features/creationBrief/useCreationBriefLifecycle'
import './CreationBriefPage.css'

const { Paragraph, Text, Title } = Typography
const { TextArea } = Input

interface CreationBriefFormValues {
  brief: string
  genre: string
  target_audience: string
  platform: string
  target_words: number
  target_chapters: number
  world_tone: string
  story_structure: string
  pacing: string
  special_requirements: string
  avoid: string
  concept_title: string
  concept_logline: string
  concept_premise: string
  concept_world_hook: string
  concept_core_conflict: string
  concept_story_engine: string
  concept_opening_hook: string
  concept_differentiators: string
  concept_risks: string
  writing_style: string
  narrative_perspective: string
  sentence_rhythm: string
  language_style: string
  style_rules: string
  forbidden_patterns: string
}

function textValue(value: unknown): string {
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.map(String).join('\n')
  if (value && typeof value === 'object') return JSON.stringify(value, null, 2)
  return value == null ? '' : String(value)
}

function numberValue(value: unknown, fallback: number): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
}

function splitLines(value: unknown): string[] {
  return String(value || '')
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function artifactStatus(context: CreationContext | null, key: string): string {
  return context?.artifact_statuses?.[key] || 'pending'
}

function statusLabel(status: string) {
  if (status === 'confirmed') return { label: '已确认', color: 'success' }
  if (status === 'generated') return { label: '可编辑', color: 'processing' }
  if (status === 'stale') return { label: '已修改', color: 'warning' }
  return { label: '待补充', color: 'default' }
}

function CreationBriefPage({ projectId }: { projectId: string }) {
  const [form] = Form.useForm<CreationBriefFormValues>()
  const [session, setSession] = useState<CreationSessionSummary | null>(null)
  const [context, setContext] = useState<CreationContext | null>(null)
  const [loading, setLoading] = useState(true)
  const [initializing, setInitializing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [remoteChangePending, setRemoteChangePending] = useState(false)
  const requestIdRef = useRef(0)
  const { refreshKey, triggerRefresh } = useAiPanelContext()

  const hydrateForm = useCallback((next: CreationContext | null) => {
    const constraints = next?.constraints || {}
    const selected = next?.creative_direction?.selected || {}
    const worldStyle = next?.world_style || {}
    form.setFieldsValue({
      brief: textValue(constraints.brief),
      genre: textValue(constraints.genre),
      target_audience: textValue(constraints.target_audience),
      platform: textValue(constraints.platform),
      target_words: numberValue(constraints.target_words, 600_000),
      target_chapters: numberValue(constraints.target_chapters, 240),
      world_tone: textValue(constraints.world_tone || worldStyle.world_tone),
      story_structure: textValue(constraints.story_structure || worldStyle.story_structure),
      pacing: textValue(constraints.pacing || worldStyle.pacing),
      special_requirements: textValue(constraints.special_requirements),
      avoid: textValue(constraints.avoid),
      concept_title: textValue(selected.title),
      concept_logline: textValue(selected.logline),
      concept_premise: textValue(selected.premise),
      concept_world_hook: textValue(selected.world_hook),
      concept_core_conflict: textValue(selected.core_conflict),
      concept_story_engine: textValue(selected.story_engine),
      concept_opening_hook: textValue(selected.opening_hook),
      concept_differentiators: textValue(selected.differentiators),
      concept_risks: textValue(selected.risks),
      writing_style: textValue(constraints.writing_style || worldStyle.writing_style),
      narrative_perspective: textValue(worldStyle.narrative_perspective || worldStyle.perspective),
      sentence_rhythm: textValue(worldStyle.sentence_rhythm),
      language_style: textValue(worldStyle.language_style || worldStyle.prose_style),
      style_rules: textValue(worldStyle.style_rules),
      forbidden_patterns: textValue(worldStyle.forbidden_patterns),
    })
    setDirty(false)
    setRemoteChangePending(false)
  }, [form])

  const loadBrief = useCallback(async (quiet = false) => {
    const requestId = ++requestIdRef.current
    if (!quiet) setLoading(true)
    setLoadError(null)
    try {
      const response = await fetchCreationBrief(projectId)
      if (requestId !== requestIdRef.current) return
      setSession(response.data.data.session)
      setContext(response.data.data.context)
      if (response.data.data.context) {
        hydrateForm(response.data.data.context)
      } else {
        setDirty(false)
        setRemoteChangePending(false)
      }
    } catch (error: any) {
      if (requestId !== requestIdRef.current) return
      setLoadError(error.message || '创作设定读取失败')
    } finally {
      if (requestId === requestIdRef.current) setLoading(false)
    }
  }, [hydrateForm, projectId])

  useCreationBriefLifecycle({
    loadBrief,
    dirty,
    refreshKey,
    onRemoteChangePending: setRemoteChangePending,
  })

  const initializeBrief = async () => {
    setInitializing(true)
    try {
      const response = await ensureCreationBrief(projectId)
      setSession(response.data.data.session)
      setContext(response.data.data.context)
      hydrateForm(response.data.data.context)
      message.success('创作设定已建立，现有作品信息已作为初始值')
      triggerRefresh()
    } catch (error: any) {
      message.error(error.message || '创作设定建立失败')
    } finally {
      setInitializing(false)
    }
  }

  const confirmReload = () => {
    const reload = () => void loadBrief()
    if (!dirty) {
      reload()
      return
    }
    Modal.confirm({
      title: '放弃尚未保存的创作设定？',
      content: '刷新会以服务器上的最新版本替换当前输入。',
      okText: '放弃并刷新',
      cancelText: '继续编辑',
      onOk: reload,
    })
  }

  const saveBrief = async () => {
    if (!session || !context) return
    let values: CreationBriefFormValues
    try {
      values = await form.validateFields()
    } catch {
      message.warning('请先修正标出的字段')
      return
    }
    setSaving(true)
    try {
      const response = await updateCreationBrief(projectId, {
          expected_revision: context.revision ?? session.revision,
          constraints: {
            brief: values.brief.trim(),
            genre: values.genre.trim(),
            target_audience: values.target_audience.trim(),
            platform: values.platform.trim(),
            target_words: values.target_words,
            target_chapters: values.target_chapters,
            world_tone: values.world_tone.trim(),
            story_structure: values.story_structure.trim(),
            pacing: values.pacing.trim(),
            writing_style: values.writing_style.trim(),
            special_requirements: splitLines(values.special_requirements),
            avoid: splitLines(values.avoid),
          },
          creative_direction: {
            selected: {
              title: values.concept_title.trim(),
              logline: values.concept_logline.trim(),
              premise: values.concept_premise.trim(),
              world_hook: values.concept_world_hook.trim(),
              core_conflict: values.concept_core_conflict.trim(),
              story_engine: values.concept_story_engine.trim(),
              opening_hook: values.concept_opening_hook.trim(),
              differentiators: splitLines(values.concept_differentiators),
              risks: splitLines(values.concept_risks),
            },
          },
          world_style: {
            writing_style: values.writing_style.trim(),
            narrative_perspective: values.narrative_perspective.trim(),
            sentence_rhythm: splitLines(values.sentence_rhythm),
            language_style: values.language_style.trim(),
            style_rules: splitLines(values.style_rules),
            forbidden_patterns: splitLines(values.forbidden_patterns),
          },
      })
      const saved = response.data.data
      setSession((current) => current ? { ...current, revision: saved.revision } : current)
      setContext(saved.creation)
      hydrateForm(saved.creation)
      message.success('创作设定已保存，并已进入后续写作上下文')
      triggerRefresh()
    } catch (error: any) {
      const detail = error.message || '创作设定保存失败'
      if (String(detail).includes('变化') || String(detail).includes('版本')) {
        setRemoteChangePending(true)
      }
      message.error(detail)
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <div className="creation-brief-loading" role="status"><Spin /><span>正在读取创作设定…</span></div>
  }

  const constraintStatus = statusLabel(artifactStatus(context, 'constraints'))
  const directionStatus = statusLabel(artifactStatus(context, 'concepts'))
  const styleStatus = statusLabel(artifactStatus(context, 'world_style'))

  return (
    <div className="creation-brief-page">
      <header className="creation-brief-header">
        <div>
          <Text className="creation-brief-kicker">CREATIVE NORTH STAR</Text>
          <Title level={2}>创作设定</Title>
          <Paragraph>维护这部作品持续有效的创作意图，而不是回到立项流程重新走一遍。</Paragraph>
        </div>
        <Space wrap>
          {context && (
            <>
              <Badge status={dirty ? 'warning' : 'success'} text={dirty ? '有未保存修改' : '已接入后续创作'} />
              <Tag>v{context.revision}</Tag>
            </>
          )}
          <Button icon={<ReloadOutlined />} disabled={saving} onClick={confirmReload}>刷新</Button>
          {context && (
            <Button type="primary" icon={<SaveOutlined />} loading={saving} disabled={!dirty} onClick={() => void saveBrief()}>
              保存创作设定
            </Button>
          )}
        </Space>
      </header>

      {loadError && <Alert type="error" showIcon message="创作设定暂时无法读取" description={loadError} action={<Button onClick={() => void loadBrief()}>重试</Button>} />}
      {remoteChangePending && (
        <Alert
          type="warning"
          showIcon
          message="项目助手或其他窗口更新了创作设定"
          description="当前输入没有被覆盖。请先决定保存当前版本，或刷新读取服务器上的新版本。"
          action={<Button size="small" onClick={confirmReload}>查看最新版本</Button>}
        />
      )}

      {!context || !session ? (
        <Card className="creation-brief-empty-card">
          <Form form={form} component={false} />
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              <div className="creation-brief-empty-copy">
                <Title level={4}>这个作品还没有可编辑的创作设定</Title>
                <Paragraph>常见于文本导入或旧版本创建的作品。建立后会从现有作品简介和文风设置开始，不会修改任何章节。</Paragraph>
              </div>
            }
          >
            <Button type="primary" size="large" icon={<DatabaseOutlined />} loading={initializing} onClick={() => void initializeBrief()}>
              建立创作设定
            </Button>
          </Empty>
        </Card>
      ) : (
        <>
          <section className="creation-brief-impact" aria-label="创作设定生效范围">
            <div><SafetyCertificateOutlined /><span><strong>单一事实源</strong><small>与立项数据共用同一版本</small></span></div>
            <div><RobotOutlined /><span><strong>项目助手可读写</strong><small>修改后刷新即可看见</small></span></div>
            <div><CompassOutlined /><span><strong>API 与 CLI 写作生效</strong><small>作为高优先级上下文传入</small></span></div>
          </section>
          <Alert
            type="info"
            showIcon
            message="保存只影响后续创作，不会反向改写已有章节"
            description="目标篇幅、创意核心和文风会进入项目助手及后续正文任务；已写内容仍由你决定是否修改。"
          />
          <Form
            form={form}
            layout="vertical"
            className="creation-brief-form"
            onValuesChange={() => setDirty(true)}
          >
            <Tabs
              defaultActiveKey="constraints"
              items={[
                {
                  key: 'constraints',
                  forceRender: true,
                  label: <Space><SafetyCertificateOutlined />创作约束<Tag color={constraintStatus.color}>{constraintStatus.label}</Tag></Space>,
                  children: (
                    <section className="creation-brief-sheet">
                      <div className="creation-brief-sheet-heading">
                        <Text className="creation-brief-index">01</Text>
                        <div><Title level={3}>创作约束</Title><Paragraph>定义边界、规模与叙事承诺，帮助模型知道什么必须坚持、什么不能碰。</Paragraph></div>
                      </div>
                      <Form.Item name="brief" label="创作核心" extra="用一两段话说明这部小说最终想讲什么。">
                        <TextArea autoSize={{ minRows: 3, maxRows: 8 }} placeholder="例如：一个用可验证实验挑战宗族修炼秩序的成长故事" />
                      </Form.Item>
                      <div className="creation-brief-grid creation-brief-grid-3">
                        <Form.Item name="genre" label="作品类型"><Input placeholder="东方玄幻 / 悬疑推理" /></Form.Item>
                        <Form.Item name="target_audience" label="目标读者"><Input placeholder="成年大众 / 男频读者" /></Form.Item>
                        <Form.Item name="platform" label="发布平台"><Input placeholder="起点 / 番茄 / 暂不确定" /></Form.Item>
                      </div>
                      <div className="creation-brief-grid">
                        <Form.Item name="target_words" label="目标字数" rules={[{ required: true, message: '请输入目标字数' }]}><InputNumber min={10_000} max={10_000_000} step={10_000} style={{ width: '100%' }} /></Form.Item>
                        <Form.Item name="target_chapters" label="目标章节数" rules={[{ required: true, message: '请输入目标章节数' }]}><InputNumber min={1} max={5_000} style={{ width: '100%' }} /></Form.Item>
                      </div>
                      <div className="creation-brief-grid creation-brief-grid-3">
                        <Form.Item name="world_tone" label="世界基调"><TextArea autoSize={{ minRows: 2, maxRows: 6 }} /></Form.Item>
                        <Form.Item name="story_structure" label="故事结构"><TextArea autoSize={{ minRows: 2, maxRows: 6 }} /></Form.Item>
                        <Form.Item name="pacing" label="叙事节奏"><TextArea autoSize={{ minRows: 2, maxRows: 6 }} /></Form.Item>
                      </div>
                      <div className="creation-brief-grid">
                        <Form.Item name="special_requirements" label="必须遵守" extra="每行一条，越具体越容易在写作中执行。"><TextArea autoSize={{ minRows: 4, maxRows: 10 }} placeholder={'信息必须跨章一致\n升级必须付出可见代价'} /></Form.Item>
                        <Form.Item name="avoid" label="必须避免" extra="每行一条，可写题材雷区、情节禁区或表达禁忌。"><TextArea autoSize={{ minRows: 4, maxRows: 10 }} placeholder={'不靠误会拖延冲突\n不临时增加无铺垫能力'} /></Form.Item>
                      </div>
                    </section>
                  ),
                },
                {
                  key: 'direction',
                  forceRender: true,
                  label: <Space><BulbOutlined />创意方向<Tag color={directionStatus.color}>{directionStatus.label}</Tag></Space>,
                  children: (
                    <section className="creation-brief-sheet">
                      <div className="creation-brief-sheet-heading">
                        <Text className="creation-brief-index">02</Text>
                        <div><Title level={3}>创意方向</Title><Paragraph>保存当前真正采用的故事方向，而不是堆放多个互相冲突的备选方案。</Paragraph></div>
                      </div>
                      <div className="creation-brief-grid">
                        <Form.Item name="concept_title" label="方向标题"><Input placeholder="经脉迷局" /></Form.Item>
                        <Form.Item name="concept_logline" label="一句话故事"><Input placeholder="主角是谁、想做什么、最大的阻力是什么" /></Form.Item>
                      </div>
                      <Form.Item name="concept_premise" label="核心前提"><TextArea autoSize={{ minRows: 3, maxRows: 8 }} /></Form.Item>
                      <div className="creation-brief-grid">
                        <Form.Item name="concept_world_hook" label="世界钩子"><TextArea autoSize={{ minRows: 3, maxRows: 8 }} /></Form.Item>
                        <Form.Item name="concept_core_conflict" label="核心冲突"><TextArea autoSize={{ minRows: 3, maxRows: 8 }} /></Form.Item>
                      </div>
                      <div className="creation-brief-grid">
                        <Form.Item name="concept_story_engine" label="持续故事引擎"><TextArea autoSize={{ minRows: 3, maxRows: 8 }} placeholder="什么机制可以持续制造事件、选择与代价" /></Form.Item>
                        <Form.Item name="concept_opening_hook" label="开篇钩子"><TextArea autoSize={{ minRows: 3, maxRows: 8 }} /></Form.Item>
                      </div>
                      <div className="creation-brief-grid">
                        <Form.Item name="concept_differentiators" label="差异点" extra="每行一条"><TextArea autoSize={{ minRows: 4, maxRows: 10 }} /></Form.Item>
                        <Form.Item name="concept_risks" label="创作风险" extra="每行一条，提前提醒后续写作"><TextArea autoSize={{ minRows: 4, maxRows: 10 }} /></Form.Item>
                      </div>
                    </section>
                  ),
                },
                {
                  key: 'style',
                  forceRender: true,
                  label: <Space><FontSizeOutlined />文风<Tag color={styleStatus.color}>{styleStatus.label}</Tag></Space>,
                  children: (
                    <section className="creation-brief-sheet">
                      <div className="creation-brief-sheet-heading">
                        <Text className="creation-brief-index">03</Text>
                        <div><Title level={3}>文风</Title><Paragraph>把抽象审美转换成可执行规则，让不同模型仍然写出同一部作品。</Paragraph></div>
                      </div>
                      <Form.Item name="writing_style" label="正文风格总则" extra="这是后续正文任务最优先读取的文风说明。">
                        <TextArea autoSize={{ minRows: 4, maxRows: 12 }} placeholder="例如：克制冷峻，以动作和可验证细节推进；不替人物解释情绪。" />
                      </Form.Item>
                      <div className="creation-brief-grid">
                        <Form.Item name="narrative_perspective" label="叙事视角"><Input placeholder="第三人称限知，跟随主角感知" /></Form.Item>
                        <Form.Item name="language_style" label="语言质感"><Input placeholder="准确、节制、少形容词" /></Form.Item>
                      </div>
                      <Form.Item name="sentence_rhythm" label="句式与节奏" extra="每行一条"><TextArea autoSize={{ minRows: 3, maxRows: 8 }} placeholder={'危机段落使用短句\n余波段落允许较长句'} /></Form.Item>
                      <div className="creation-brief-grid">
                        <Form.Item name="style_rules" label="必须采用的写法" extra="每行一条"><TextArea autoSize={{ minRows: 5, maxRows: 12 }} /></Form.Item>
                        <Form.Item name="forbidden_patterns" label="禁用表达" extra="每行一条"><TextArea autoSize={{ minRows: 5, maxRows: 12 }} /></Form.Item>
                      </div>
                    </section>
                  ),
                },
              ]}
            />
          </Form>
        </>
      )}
    </div>
  )
}

export default CreationBriefPage
