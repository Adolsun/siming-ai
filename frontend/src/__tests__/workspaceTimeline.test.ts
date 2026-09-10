import { describe, expect, it } from 'vitest'
import { mergeWorkspaceTimeline } from '../components/assistant/constants'
import type { WorkspaceAssistantMessage } from '../components/assistant/types'

const msg = (id: string, time?: string, sequence?: number): WorkspaceAssistantMessage => ({
  id, role: 'assistant', content: id, created_at: time, sequence_no: sequence,
})

describe('workspace timeline', () => {
  it('places completed cataloging before the later user request and reply', () => {
    const messages = [
      msg('new-reply', '2026-09-10T03:27:21.402334', 12),
      msg('old-draft', '2026-09-09T12:07:07Z', 10),
      { ...msg('new-user', '2026-09-10T03:27:21.402333', 11), role: 'user' as const },
    ]
    const notices = [msg('completed', '2026-09-10T03:04:02Z'), msg('old-job', '2026-09-09T13:04:24Z')]
    expect(mergeWorkspaceTimeline(messages, notices).map(item => item.id)).toEqual([
      'old-draft', 'old-job', 'completed', 'new-user', 'new-reply',
    ])
    expect(messages[0].id).toBe('new-reply')
  })

  it('keeps a just-sent message visible after old notices before persistence', () => {
    const messages = [{ ...msg('sending'), role: 'user' as const }, msg('streaming')]
    expect(mergeWorkspaceTimeline(messages, [msg('old-job', '2026-09-10T03:04:02Z')]).map(item => item.id))
      .toEqual(['old-job', 'sending', 'streaming'])
  })

  it('preserves server sequence even when historical clocks are out of order', () => {
    const messages = [msg('second', '2026-09-10T03:00:00Z', 2), msg('first', '2026-09-10T04:00:00Z', 1)]
    const result = mergeWorkspaceTimeline(messages, [msg('notice', '2026-09-10T03:30:00Z')])
    expect(result.filter(item => item.sequence_no).map(item => item.id)).toEqual(['first', 'second'])
    expect(result.filter(item => item.id === 'notice')).toHaveLength(1)
  })
})
