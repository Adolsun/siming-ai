import { describe, expect, it } from 'vitest'
import { collectSelectedPath, collectTreeKeys } from '../pages/OutlinePage'
import { chapterStatusLabel } from '../pages/WriterPage'

const tree = [{
  id: 'volume-1',
  children: [{
    id: 'chapter-1',
    children: [{ id: 'section-1', children: [] }],
  }],
}] as any

describe('authoring UI navigation helpers', () => {
  it('opens only the selected ancestry instead of the entire outline', () => {
    expect(collectSelectedPath(tree, 'chapter-1')).toEqual(['volume-1', 'chapter-1'])
    expect(collectTreeKeys(tree)).toEqual(['volume-1', 'chapter-1', 'section-1'])
  })

  it('uses Chinese labels for persisted chapter states', () => {
    expect(chapterStatusLabel('pending')).toBe('待规划')
    expect(chapterStatusLabel('in_progress')).toBe('进行中')
    expect(chapterStatusLabel('completed')).toBe('已完成')
    expect(chapterStatusLabel('future_state')).toBe('未知状态')
  })
})
