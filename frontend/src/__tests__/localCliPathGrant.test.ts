import { describe, expect, it } from 'vitest'
import { extractExplicitLocalPaths } from '../utils/localCliPathGrant'

describe('extractExplicitLocalPaths', () => {
  it('extracts quoted paths with spaces and ordinary absolute paths', () => {
    expect(extractExplicitLocalPaths(
      '请读取 "C:\\Novel Notes\\世界观.md"，再参考 D:\\books\\outline.txt',
    )).toEqual([
      'C:\\Novel Notes\\世界观.md',
      'D:\\books\\outline.txt',
    ])
  })

  it('deduplicates paths without treating relative text as a grant candidate', () => {
    expect(extractExplicitLocalPaths(
      '读取 C:\\books\\outline.txt 和 `c:\\books\\outline.txt`，不要读取 notes\\private.txt',
    )).toEqual(['C:\\books\\outline.txt'])
  })

  it('supports file URIs', () => {
    expect(extractExplicitLocalPaths('读取 file:///C:/books/world.md')).toEqual([
      'C:/books/world.md',
    ])
  })

  it('recognizes an unquoted supported file path containing spaces', () => {
    expect(extractExplicitLocalPaths(
      '请读取 C:\\Novel Notes\\世界观.md，再概括重点',
    )).toEqual(['C:\\Novel Notes\\世界观.md'])
  })

  it('ignores malformed file URIs instead of interrupting message submission', () => {
    expect(extractExplicitLocalPaths('读取 file:///C:/books/%E0%A4%A.md')).toEqual([])
  })
})
