import { describe, expect, it } from 'vitest'
import type { OperationRun } from '../shared/api/contracts'
import { projectAutoCatalogingMessages } from '../components/assistant/catalogingNotifications'

function operation(overrides: Partial<OperationRun> = {}): OperationRun {
  return {
    id: 'operation-1',
    source_kind: 'cataloging',
    source_id: 'job-1',
    project_id: 'project-1',
    title: '《第二章 吐纳》自动建档',
    status: 'running',
    health_status: 'active',
    can_pause: true,
    can_cancel: true,
    can_retry: true,
    elapsed_seconds: 0,
    progress: { mode: 'determinate', current: 0, total: 1 },
    tool_mode: 'auto_chapter_write:internal_llm',
    created_at: '2026-08-12T10:00:00Z',
    updated_at: '2026-08-12T10:00:01Z',
    ...overrides,
  }
}

describe('projectAutoCatalogingMessages', () => {
  it('announces the quality warning while auto cataloging is running', () => {
    const messages = projectAutoCatalogingMessages([operation()], 'project-1')

    expect(messages).toHaveLength(1)
    expect(messages[0].content).toContain('正在自动建档')
    expect(messages[0].content).toContain('立即生成下一章可能影响上下文质量')
  })

  it('adds a durable completion notification', () => {
    const messages = projectAutoCatalogingMessages([
      operation({
        status: 'completed',
        completed_at: '2026-08-12T10:00:20Z',
        result_summary: '作品建档完成，共处理 1 章',
      }),
    ], 'project-1')

    expect(messages).toHaveLength(2)
    expect(messages[1].content).toContain('自动建档已完成')
    expect(messages[1].content).toContain('现在可以继续生成下一章')
    expect(messages[1].data?.outcome).toBe('completed_with_tools')
  })

  it('does not leak another project or manual cataloging task into chat', () => {
    const messages = projectAutoCatalogingMessages([
      operation({ project_id: 'project-2' }),
      operation({ id: 'manual', tool_mode: 'internal_llm' }),
    ], 'project-1')

    expect(messages).toEqual([])
  })

  it('reports an incomplete task as blocked instead of success', () => {
    const messages = projectAutoCatalogingMessages([
      operation({ status: 'paused', next_action: '缺少角色关系候选' }),
    ], 'project-1')

    expect(messages[1].status).toBe('error')
    expect(messages[1].content).toContain('缺少角色关系候选')
    expect(messages[1].data?.outcome).toBe('blocked')
  })
})
