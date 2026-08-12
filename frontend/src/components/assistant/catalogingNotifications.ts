import type { OperationRun } from '../../shared/api/contracts'
import type { WorkspaceAssistantMessage, WorkspaceAssistantOutcome } from './types'

const AUTO_CATALOGING_MODE = 'auto_chapter_write:'
const ATTENTION_STATUSES = new Set<OperationRun['status']>(['waiting_user', 'paused'])
const TERMINAL_STATUSES = new Set<OperationRun['status']>([
  'completed',
  'failed',
  'cancelled',
  'interrupted',
])

function operationTime(operation: OperationRun) {
  const value = operation.created_at || operation.updated_at || ''
  const parsed = value ? new Date(value).getTime() : Number.NaN
  return Number.isFinite(parsed) ? parsed : 0
}
function chapterLabel(operation: OperationRun) {
  const title = String(operation.title || '').trim()
  const withoutSuffix = title.replace(/自动建档.*$/, '').trim()
  return withoutSuffix || '当前章节'
}

function assistantMessage(
  operation: OperationRun,
  phase: 'started' | 'terminal',
  content: string,
  status: string,
  outcome?: WorkspaceAssistantOutcome,
): WorkspaceAssistantMessage {
  return {
    id: `cataloging-operation-${operation.id}-${phase}`,
    role: 'assistant',
    content,
    status,
    created_at: phase === 'started'
      ? operation.created_at || operation.updated_at || undefined
      : operation.completed_at || operation.updated_at || undefined,
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

function terminalMessage(operation: OperationRun): WorkspaceAssistantMessage | null {
  const label = chapterLabel(operation)
  const detail = String(
    operation.result_summary
    || operation.result?.summary
    || operation.next_action
    || operation.current_message
    || '',
  ).trim()

  if (operation.status === 'completed') {
    const content = `${label}自动建档已完成，角色、关系、世界观、大纲与叙事治理数据已通过完整性校验。现在可以继续生成下一章。${detail ? `\n${detail}` : ''}`
    return assistantMessage(operation, 'terminal', content, 'completed', 'completed_with_tools')
  }
  if (operation.status === 'waiting_user') {
    const content = `${label}自动建档需要你确认候选后才能完成。请先打开“作品建档”处理，暂时不要继续生成下一章。${detail ? `\n${detail}` : ''}`
    return assistantMessage(operation, 'terminal', content, 'blocked', 'waiting_user')
  }
  if (operation.status === 'paused') {
    const content = `${label}自动建档已暂停，数据尚未形成完整闭环。请在“作品建档”重试或处理当前问题。${detail ? `\n${detail}` : ''}`
    return assistantMessage(operation, 'terminal', content, 'error', 'blocked')
  }
  if (operation.status === 'cancelled') {
    const content = `${label}自动建档已取消；本章档案可能仍是旧版本。${detail ? `\n${detail}` : ''}`
    return assistantMessage(operation, 'terminal', content, 'aborted', 'cancelled')
  }
  if (operation.status === 'interrupted') {
    const content = `${label}自动建档被中断，尚未完成数据一致性校验。请从任务中心恢复或重试。${detail ? `\n${detail}` : ''}`
    return assistantMessage(operation, 'terminal', content, 'error', 'interrupted')
  }
  if (operation.status === 'failed') {
    const content = `${label}自动建档失败，系统没有把不完整候选当作成功写入。请在“作品建档”查看原因并重试。${detail ? `\n${detail}` : ''}`
    return assistantMessage(operation, 'terminal', content, 'error', 'failed')
  }
  return null
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
    .slice(-12)

  return relevant.flatMap((operation) => {
    const label = chapterLabel(operation)
    const start = assistantMessage(
      operation,
      'started',
      `${label}已保存，正在自动建档。立即生成下一章可能影响上下文质量，请耐心等待建档完成。`,
      'running',
    )
    if (!TERMINAL_STATUSES.has(operation.status) && !ATTENTION_STATUSES.has(operation.status)) {
      return [start]
    }
    const terminal = terminalMessage(operation)
    return terminal ? [start, terminal] : [start]
  })
}
