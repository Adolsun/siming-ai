import { afterEach, describe, expect, it, vi } from 'vitest'
import { motionAwareScrollBehavior } from '../utils/motion'

function mockReducedMotion(matches: boolean) {
  vi.spyOn(window, 'matchMedia').mockImplementation((query) => ({
    matches: query === '(prefers-reduced-motion: reduce)' && matches,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }))
}

describe('motionAwareScrollBehavior', () => {
  afterEach(() => vi.restoreAllMocks())

  it('uses instant scrolling when reduced motion is requested', () => {
    mockReducedMotion(true)
    expect(motionAwareScrollBehavior()).toBe('auto')
  })

  it('keeps smooth scrolling for the normal motion preference', () => {
    mockReducedMotion(false)
    expect(motionAwareScrollBehavior()).toBe('smooth')
  })
})
