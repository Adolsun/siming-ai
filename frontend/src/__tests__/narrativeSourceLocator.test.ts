import { describe, expect, it } from 'vitest'
import { findEvidenceRange, resolveNarrativeSourceRange } from '../features/narrativeGovernance/sourceLocator'

describe('narrative source locator', () => {
  it('locates an exact quoted excerpt inside explanatory evidence', () => {
    const content = '她推开院门。\n石狮眉心忽然亮起一道细纹，院中众人同时回头。\n风又静了。'
    const range = findEvidenceRange(content, '发现依据：“石狮眉心忽然亮起一道细纹，院中众人同时回头。”')

    expect(range).not.toBeNull()
    expect(content.slice(range!.start, range!.end)).toContain('石狮眉心忽然亮起')
  })

  it('tolerates whitespace and punctuation differences', () => {
    const content = '陆景珩抬眼，低声道：“别回头。”'
    const range = findEvidenceRange(content, '陆景珩抬眼低声道：别回头')

    expect(range).not.toBeNull()
    expect(content.slice(range!.start, range!.end)).toContain('陆景珩')
  })

  it('returns null instead of selecting unrelated text', () => {
    expect(findEvidenceRange('正文没有这一条线索。', '另一处完全不同的证据')).toBeNull()
  })

  it('prefers a valid server character range', () => {
    const content = '开头。\n石狮子眉心闪过一道细纹。\n结尾。'
    const excerpt = '石狮子眉心闪过一道细纹。'
    const start = content.indexOf(excerpt)
    expect(resolveNarrativeSourceRange(content, {
      evidence: '',
      sourceExcerpt: excerpt,
      sourceStart: start,
      sourceEnd: start + excerpt.length,
    })).toEqual({ start, end: start + excerpt.length })
  })

  it('re-anchors by excerpt after chapter text moved', () => {
    const content = '新增开场。\n石狮子眉心闪过一道细纹。\n结尾。'
    const excerpt = '石狮子眉心闪过一道细纹。'
    const start = content.indexOf(excerpt)
    expect(resolveNarrativeSourceRange(content, {
      evidence: '',
      sourceExcerpt: excerpt,
      sourceStart: 0,
      sourceEnd: 4,
    })).toEqual({ start, end: start + excerpt.length })
  })
})
