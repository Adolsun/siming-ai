import { DatabaseOutlined, SaveOutlined } from '@ant-design/icons'
import { Button } from 'antd'

export type ChapterSaveMode = 'save_only' | 'save_and_catalog'

interface WriterSaveActionsProps {
  hasEditor: boolean
  creating: boolean
  dirty: boolean
  hasTitle: boolean
  catalogingRequired: boolean
  catalogingRunning: boolean
  busy: boolean
  saveMode: ChapterSaveMode | null
  onSave: (mode: ChapterSaveMode) => void
}

export function WriterSaveActions({
  hasEditor, creating, dirty, hasTitle, catalogingRequired,
  catalogingRunning, busy, saveMode, onSave,
}: WriterSaveActionsProps) {
  const changed = creating || dirty
  const unavailable = !hasEditor || !hasTitle || busy || catalogingRunning
  return (
    <div className="writer-save-actions" role="group" aria-label="保存与建档">
      <Button
        type={changed ? 'primary' : 'default'}
        icon={<SaveOutlined />}
        aria-label="保存正文"
        aria-keyshortcuts="Control+s Meta+s"
        disabled={unavailable || !changed}
        loading={busy && saveMode === 'save_only'}
        onClick={() => onSave('save_only')}
      >
        保存正文
      </Button>
      <Button
        type={!changed && catalogingRequired ? 'primary' : 'default'}
        icon={<DatabaseOutlined />}
        aria-label={catalogingRunning ? '建档中' : changed ? '保存并建档' : '开始建档'}
        disabled={unavailable || (!changed && !catalogingRequired)}
        loading={catalogingRunning || (busy && saveMode === 'save_and_catalog')}
        onClick={() => onSave('save_and_catalog')}
      >
        {catalogingRunning ? '建档中' : changed ? '保存并建档' : '开始建档'}
      </Button>
    </div>
  )
}

export function WriterSaveGuidance({
  creating, dirty, hasTitle, catalogingRequired, catalogingRunning, busy,
}: Omit<WriterSaveActionsProps, 'hasEditor' | 'saveMode' | 'onSave'>) {
  let title: string
  let description: string
  if (busy) {
    title = '正在提交，请稍候'
    description = '完成后会显示保存结果；提交期间暂时锁定编辑，避免后续修改被覆盖。'
  } else if (catalogingRunning) {
    title = '已保存的正文正在建档'
    description = dirty
      ? '当前修改还未保存。请等本次建档结束，再保存这些修改。'
      : '正在根据已保存正文更新故事资料。完成后你再决定何时写下一章。'
  } else if (!hasTitle) {
    title = '先填写章节标题'
    description = '有标题后即可保存。可以先保存正文，满意后再建档。'
  } else if (creating || dirty) {
    title = creating ? '正文尚未保存' : '当前修改尚未保存'
    description = '保存正文只保留本次编辑；保存并建档还会根据正文更新故事资料。'
  } else if (catalogingRequired) {
    title = '正文已保存，等待建档'
    description = '你可以继续修改本章。建档完成后，AI 才能继续下一章。'
  } else {
    title = '当前正文已建档'
    description = '可以继续修改，或由你决定何时让 AI 写下一章。剧情或设定变化后需要重新建档。'
  }
  return (
    <div className="writer-save-guidance" aria-label="写作进度与下一步">
      <strong>{title}</strong>
      <span>{description}</span>
      <span className="writer-save-shortcut">Ctrl / ⌘ + S：只保存正文</span>
    </div>
  )
}
