export interface NarrativeSourceLocator {
  projectId: string
  chapterId: string
  evidence: string
  sourceExcerpt?: string
  sourceStart?: number
  sourceEnd?: number
  governanceItemId?: string
  sourceVersion?: number
  createdAt: string
}

export interface TextRange {
  start: number
  end: number
}

const STORAGE_PREFIX = 'siming:narrative-source:'
const MAX_EVIDENCE_LENGTH = 8_000

function storageKey(locatorKey: string) {
  return `${STORAGE_PREFIX}${locatorKey}`
}

export function storeNarrativeSourceLocator(
  locator: Omit<NarrativeSourceLocator, 'createdAt'>,
): string | null {
  const hasText = Boolean(locator.evidence.trim() || locator.sourceExcerpt?.trim())
  const hasRange = Number.isInteger(locator.sourceStart)
    && Number.isInteger(locator.sourceEnd)
    && Number(locator.sourceEnd) > Number(locator.sourceStart)
  if (typeof window === 'undefined' || !locator.chapterId || (!hasText && !hasRange)) return null
  const locatorKey = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
  try {
    window.sessionStorage.setItem(storageKey(locatorKey), JSON.stringify({
      ...locator,
      evidence: locator.evidence.slice(0, MAX_EVIDENCE_LENGTH),
      sourceExcerpt: locator.sourceExcerpt?.slice(0, MAX_EVIDENCE_LENGTH),
      createdAt: new Date().toISOString(),
    }))
    return locatorKey
  } catch {
    return null
  }
}

export function readNarrativeSourceLocator(locatorKey?: string): NarrativeSourceLocator | null {
  if (typeof window === 'undefined' || !locatorKey) return null
  try {
    const raw = window.sessionStorage.getItem(storageKey(locatorKey))
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<NarrativeSourceLocator>
    const hasText = Boolean(String(parsed.evidence || '').trim() || String(parsed.sourceExcerpt || '').trim())
    const hasRange = Number.isInteger(parsed.sourceStart)
      && Number.isInteger(parsed.sourceEnd)
      && Number(parsed.sourceEnd) > Number(parsed.sourceStart)
    if (!parsed.projectId || !parsed.chapterId || (!hasText && !hasRange)) return null
    return {
      projectId: parsed.projectId,
      chapterId: parsed.chapterId,
      evidence: String(parsed.evidence || ''),
      sourceExcerpt: parsed.sourceExcerpt ? String(parsed.sourceExcerpt) : undefined,
      sourceStart: Number.isInteger(parsed.sourceStart) ? Number(parsed.sourceStart) : undefined,
      sourceEnd: Number.isInteger(parsed.sourceEnd) ? Number(parsed.sourceEnd) : undefined,
      governanceItemId: parsed.governanceItemId,
      sourceVersion: parsed.sourceVersion,
      createdAt: parsed.createdAt || new Date().toISOString(),
    }
  } catch {
    return null
  }
}

function evidenceFragments(evidence: string): string[] {
  const source = evidence.trim()
  const fragments = new Set<string>()
  if (source) fragments.add(source)

  const quotePattern = /[“「『\"]([^”」』\"]{6,})[”」』\"]/g
  for (const match of source.matchAll(quotePattern)) {
    if (match[1]?.trim()) fragments.add(match[1].trim())
  }

  source
    .split(/[\r\n]+|(?<=[。！？；!?;])/)
    .map((part) => part.replace(/^\s*(?:原文|证据|依据|正文|章节中|文中)\s*[：:]\s*/u, '').trim())
    .filter((part) => part.length >= 6)
    .forEach((part) => fragments.add(part))

  return [...fragments].sort((left, right) => right.length - left.length)
}

function normalizedTextWithMap(value: string) {
  let text = ''
  const indexes: number[] = []
  for (let index = 0; index < value.length; index += 1) {
    const normalized = value[index].normalize('NFKC').toLocaleLowerCase()
    for (const character of normalized) {
      if (/\s/u.test(character) || /[，。！？；：、“”‘’（）()【】\[\]《》<>…—·,.!?;:'"-]/u.test(character)) continue
      text += character
      indexes.push(index)
    }
  }
  return { text, indexes }
}

function normalizedRange(content: string, fragment: string): TextRange | null {
  const normalizedContent = normalizedTextWithMap(content)
  const normalizedFragment = normalizedTextWithMap(fragment).text
  if (normalizedFragment.length < 6) return null
  const normalizedStart = normalizedContent.text.indexOf(normalizedFragment)
  if (normalizedStart < 0) return null
  const start = normalizedContent.indexes[normalizedStart]
  const last = normalizedContent.indexes[normalizedStart + normalizedFragment.length - 1]
  if (start === undefined || last === undefined) return null
  return { start, end: last + 1 }
}

/** Find the strongest exact excerpt represented by a governance evidence string. */
export function findEvidenceRange(content: string, evidence: string): TextRange | null {
  if (!content || !evidence.trim()) return null
  const fragments = evidenceFragments(evidence)
  for (const fragment of fragments) {
    const exactStart = content.indexOf(fragment)
    if (exactStart >= 0) return { start: exactStart, end: exactStart + fragment.length }
  }
  for (const fragment of fragments) {
    const range = normalizedRange(content, fragment)
    if (range) return range
  }
  return null
}

/** Resolve a server-verified range first, then re-anchor by excerpt/evidence. */
export function resolveNarrativeSourceRange(
  content: string,
  locator: Pick<NarrativeSourceLocator, 'evidence' | 'sourceExcerpt' | 'sourceStart' | 'sourceEnd'>,
): TextRange | null {
  const start = locator.sourceStart
  const end = locator.sourceEnd
  if (
    Number.isInteger(start)
    && Number.isInteger(end)
    && Number(end) > Number(start)
    && Number(start) >= 0
    && Number(end) <= content.length
  ) {
    const selected = content.slice(Number(start), Number(end))
    if (!locator.sourceExcerpt || normalizedTextWithMap(selected).text === normalizedTextWithMap(locator.sourceExcerpt).text) {
      return { start: Number(start), end: Number(end) }
    }
  }
  if (locator.sourceExcerpt?.trim()) {
    const excerptRange = findEvidenceRange(content, locator.sourceExcerpt)
    if (excerptRange) return excerptRange
  }
  return findEvidenceRange(content, locator.evidence)
}
