import { useEffect, useRef } from 'react'
import { message } from 'antd'

import {
  readNarrativeSourceLocator,
  resolveNarrativeSourceRange,
} from '../narrativeGovernance/sourceLocator'

interface SourceChapter {
  id: string
  content: string
  current_version: number
}

interface WriterSourceNavigationOptions {
  projectId: string
  focusChapterId?: string
  sourceLocatorKey?: string
  chapterIds: string[]
  detail: SourceChapter | null
  confirmLeave: (callback: () => void) => void
  onFocusChapter: (chapterId: string) => void
  onEvidenceSelected: (range: { start: number; end: number }, text: string, chapterId: string) => void
}

const getContentTextArea = () => document.querySelector<HTMLTextAreaElement>(
  'textarea.writer-content-input, .writer-content-input textarea',
)

export function useWriterSourceNavigation({
  projectId,
  focusChapterId,
  sourceLocatorKey,
  chapterIds,
  detail,
  confirmLeave,
  onFocusChapter,
  onEvidenceSelected,
}: WriterSourceNavigationOptions) {
  const lastFocusedChapterIdRef = useRef<string | null>(null)
  const lastAppliedSourceLocatorRef = useRef<string | null>(null)

  useEffect(() => {
    if (
      !focusChapterId
      || lastFocusedChapterIdRef.current === focusChapterId
      || !chapterIds.includes(focusChapterId)
    ) return
    confirmLeave(() => {
      lastFocusedChapterIdRef.current = focusChapterId
      onFocusChapter(focusChapterId)
    })
  }, [chapterIds, confirmLeave, focusChapterId, onFocusChapter])

  useEffect(() => {
    if (
      !sourceLocatorKey
      || lastAppliedSourceLocatorRef.current === sourceLocatorKey
      || !detail
      || detail.id !== focusChapterId
    ) return
    const locator = readNarrativeSourceLocator(sourceLocatorKey)
    if (!locator || locator.projectId !== projectId || locator.chapterId !== detail.id) return
    lastAppliedSourceLocatorRef.current = sourceLocatorKey
    const range = resolveNarrativeSourceRange(detail.content || '', locator)
    window.requestAnimationFrame(() => {
      const editor = getContentTextArea()
      if (!editor || !range) {
        message.warning('已打开来源章节，但当前版本未找到对应原文；该段内容可能已被修改')
        return
      }
      editor.focus({ preventScroll: true })
      editor.setSelectionRange(range.end, range.end)
      editor.setSelectionRange(range.start, range.end)
      const availableScroll = Math.max(0, editor.scrollHeight - editor.clientHeight)
      const selectionRatio = range.start / Math.max(1, editor.value.length)
      editor.scrollTop = Math.max(0, Math.min(availableScroll, selectionRatio * editor.scrollHeight - editor.clientHeight * 0.35))
      if (typeof editor.scrollIntoView === 'function') {
        editor.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }
      onEvidenceSelected(range, editor.value.slice(range.start, range.end), detail.id)
      if (locator.sourceVersion && locator.sourceVersion !== detail.current_version) {
        message.info(`已定位到对应原文；治理依据来自 v${locator.sourceVersion}，当前为 v${detail.current_version}`)
      } else {
        message.success('已定位并选中治理项对应原文')
      }
    })
  }, [detail, focusChapterId, onEvidenceSelected, projectId, sourceLocatorKey])
}
