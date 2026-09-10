import { waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from '../api/client'

describe('progress stream lifetime', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('cancels the transport without reporting an intentional disconnect as an error', async () => {
    const onError = vi.fn()
    let signal: AbortSignal | undefined
    vi.stubGlobal('fetch', vi.fn((_url, options) => new Promise((_resolve, reject) => {
      signal = options.signal
      signal!.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    })))
    const stop = apiClient.stream('/projects/p/cataloging/job/stream', {}, vi.fn(), onError)
    expect(signal?.aborted).toBe(false)
    stop()
    await Promise.resolve()
    await Promise.resolve()
    expect(signal?.aborted).toBe(true)
    expect(onError).not.toHaveBeenCalled()
  })

  it('still reports real connection errors', async () => {
    const onError = vi.fn()
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Network unavailable')))
    apiClient.stream('/projects/p/cataloging/job/stream', {}, vi.fn(), onError)
    await waitFor(() => expect(onError).toHaveBeenCalledOnce())
    expect(onError.mock.calls[0][0].message).toBe('Network unavailable')
  })
})
