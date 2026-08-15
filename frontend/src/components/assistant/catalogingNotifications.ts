import type { OperationRun } from '../../shared/api/contracts'
import { apiDateTimeMs } from '../../utils/dateTime'
import type { WorkspaceAssistantMessage, WorkspaceAssistantOutcome } from './types'

const AUTO_CATALOGING_MODE = 'auto_chapter_write:'

function operationTime(operation: OperationRun) {
  const value = operation.created_at || operation.updated_at || ''
  const parsed = apiDateTimeMs(value)
  return Number.isFinite(parsed) ? parsed : 0
}
function chapterLabel(operation: OperationRun) {
  const title = String(operation.title || '').trim()
  const withoutSuffix = title.replace(/自动建档.*$/, '').trim()
  return withoutSuffix || '当前章节'
}

function appendDetail(content: string, detail: string) {
  const repeatsRunningNotice = content.includes('正在自动建档') && detail.includes('正在自动建档')
  return detail && !content.includes(detail) && !repeatsRunningNotice
    ? `${content}\n${detail}`
    : content
}

function assistantMessage(
  operation: OperationRun,
  content: string,
  status: string,
  projectId: string,
  navigationLabel: string,
  outcome?: WorkspaceAssistantOutcome,
): WorkspaceAssistantMessage {
  return {
    id: `cataloging-operation-${operation.id}`,
    role: 'assistant',
    content,
    status,
    // This is a live status message, so order it by the latest task activity.
    // Using only created_at placed it above the writer's final reply and made
    // both the reminder and its action button effectively invisible.
    created_at: operation.completed_at || operation.updated_at || operation.created_at || undefined,
    navigation_action: {
      label: navigationLabel,
      to: operation.attention?.action_url
        || operation.resume_url
        || `/project/${encodeURIComponent(projectId)}?view=cataloging`,
    },
    data: outcome
      ? {
          reply: content,
          outcome,
          tool_logs: [],
          actions: [],
          applied_actions: [],
        }
      : undefined,
  }
}

function operationMessage(operation: OperationRun, projectId: string): WorkspaceAssistantMessage {
  const label = chapterLabel(operation)
  const detail = String(
    operation.result_summary
    || operation.result?.summary
    || operation.next_action
    || operation.current_message
    || '',
  ).trim()

  if (operation.status === 'completed') {
    const content = appendDetail(
      `${label}自动建档已完成，建档结果已同步到作品资料和任务中心。现在可以继续生成下一章。`,
      detail,
    )
    return assistantMessage(operation, content, 'completed', projectId, '查看建档结果', 'completed_with_tools')
  }
  if (operation.status === 'waiting_user') {
    const content = appendDetail(
      `${label}自动建档需要你确认候选后才能完成。请先打开“作品建档”处理，暂时不要继续生成下一章。`,
      detail,
    )
    return assistantMessage(operation, content, 'blocked', projectId, '前往处理建档', 'waiting_user')
  }
  if (operation.status === 'paused') {
    const content = appendDetail(
      `${label}自动建档已暂停，数据尚未形成完整闭环。请在“作品建档”重试或处理当前问题。`,
      detail,
    )
    return assistantMessage(operation, content, 'error', projectId, '前往处理建档', 'blocked')
  }
  if (operation.status === 'cancelled') {
    const content = appendDetail(`${label}自动建档已取消；本章档案可能仍是旧版本。`, detail)
    return assistantMessage(operation, content, 'aborted', projectId, '查看建档记录', 'cancelled')
  }
  if (operation.status === 'interrupted') {
    const content = appendDetail(
      `${label}自动建档被中断，尚未完成数据一致性校验。请从任务中心恢复或重试。`,
      detail,
    )
    return assistantMessage(operation, content, 'error', projectId, '前往处理建档', 'interrupted')
  }
  if (operation.status === 'failed') {
    const content = appendDetail(
      `${label}自动建档失败，系统没有把不完整候选当作成功写入。请在“作品建档”查看原因并重试。`,
      detail,
    )
    return assistantMessage(operation, content, 'error', projectId, '前往处理建档', 'failed')
  }
  const progress = operation.progress?.total
    ? `（${operation.progress.current || 0}/${operation.progress.total}）`
    : ''
  const content = appendDetail(
    `${label}已保存，正在自动建档${progress}。立即生成下一章可能影响上下文质量，请耐心等待建档完成。`,
    detail,
  )
  return assistantMessage(operation, content, 'running', projectId, '查看建档进度')
}

/** Project auto-cataloging operations rendered as durable chat notifications. */
export function projectAutoCatalogingMessages(
  operations: OperationRun[],
  projectId: string,
): WorkspaceAssistantMessage[] {
  const relevant = operations
    .filter((operation) => (
      operation.project_id === projectId
      && operation.source_kind === 'cataloging'
      && String(operation.tool_mode || '').startsWith(AUTO_CATALOGING_MODE)
    ))
    .sort((a, b) => operationTime(a) - operationTime(b))
    .slice(-3)

  return relevant.map((operation) => operationMessage(operation, projectId))
}
