const WINDOWS_ABSOLUTE_PATH = /^[a-zA-Z]:[\\/]/
const SUPPORTED_FILE_SUFFIXES = [
  'cfg', 'conf', 'css', 'csv', 'docx', 'html', 'ini', 'java', 'js', 'json',
  'jsonl', 'jsx', 'log', 'markdown', 'md', 'mjs', 'py', 'rst', 'scss', 'sql',
  'toml', 'ts', 'tsv', 'tsx', 'txt', 'xml', 'yaml', 'yml',
].join('|')

type PathCandidate = {
  value: string
  start: number
  end: number
  protectedRange: boolean
}

function normalizeCandidate(value: string): string | null {
  let candidate = value.trim()
  if (candidate.toLowerCase().startsWith('file:///')) {
    try {
      candidate = decodeURIComponent(candidate.slice('file:///'.length))
    } catch {
      return null
    }
  }
  candidate = candidate.replace(/[，。；;、）)\]}]+$/u, '').trim()
  if (!WINDOWS_ABSOLUTE_PATH.test(candidate)) return null
  return candidate
}

/**
 * Extract only explicit Windows absolute paths from chat text.
 * Supported file paths may contain spaces; directory paths containing spaces
 * must be quoted or wrapped in backticks to keep permission detection explicit.
 */
export function extractExplicitLocalPaths(text: string): string[] {
  const candidates: PathCandidate[] = []
  const quoted = /(["'`])([a-zA-Z]:[\\/][^\r\n]*?)\1/g
  const fileUris = /file:\/\/\/[a-zA-Z]:\/[^\s"'`，。；;、）)\]}]+/gi
  const supportedFilesWithSpaces = new RegExp(
    `(?:^|[\\s（(：:])([a-zA-Z]:[\\\\/][^"'\\x60\\r\\n<>|?*]*?\\.(?:${SUPPORTED_FILE_SUFFIXES}))(?=$|[\\s，。；;、）)\\]}])`,
    'gi',
  )
  const bare = /(?:^|[\s（(：:])([a-zA-Z]:[\\/][^\s"'`<>|?*，。；;、）)\]}]+)/g

  const collect = (match: RegExpMatchArray, group: number, protectedRange: boolean) => {
    const value = match[group]
    const offset = match[0].indexOf(value)
    const start = (match.index ?? 0) + Math.max(0, offset)
    candidates.push({ value, start, end: start + value.length, protectedRange })
  }

  for (const match of text.matchAll(quoted)) collect(match, 2, true)
  for (const match of text.matchAll(fileUris)) collect(match, 0, true)
  for (const match of text.matchAll(supportedFilesWithSpaces)) collect(match, 1, true)
  for (const match of text.matchAll(bare)) {
    const value = match[1]
    const offset = match[0].indexOf(value)
    const start = (match.index ?? 0) + Math.max(0, offset)
    const overlapsExplicitCandidate = candidates.some(
      (candidate) => candidate.protectedRange
        && start >= candidate.start
        && start < candidate.end,
    )
    if (!overlapsExplicitCandidate) collect(match, 1, false)
  }
  candidates.sort((left, right) => left.start - right.start)

  const result: string[] = []
  const seen = new Set<string>()
  for (const candidate of candidates) {
    const normalized = normalizeCandidate(candidate.value)
    if (!normalized) continue
    const key = normalized.toLocaleLowerCase('en-US')
    if (!seen.has(key)) {
      seen.add(key)
      result.push(normalized)
    }
    if (result.length >= 8) break
  }
  return result
}
