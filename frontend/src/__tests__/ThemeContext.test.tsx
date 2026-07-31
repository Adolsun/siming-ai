import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { theme as antdTheme } from 'antd'
import { ThemeProvider } from '../themes/ThemeContext'

function MotionTokenProbe() {
  const { token } = antdTheme.useToken()
  return <output data-testid="motion-token">{String(token.motion)}</output>
}

describe('ThemeProvider reduced-motion integration', () => {
  afterEach(() => vi.restoreAllMocks())

  it('disables Ant Design motion and follows preference changes in real time', () => {
    let matches = true
    const changeListeners: Array<() => void> = []
    vi.spyOn(window, 'matchMedia').mockImplementation((query) => ({
      get matches() { return query === '(prefers-reduced-motion: reduce)' ? matches : false },
      media: query,
      onchange: null,
      addEventListener: (_type: string, listener: EventListenerOrEventListenerObject) => {
        if (query === '(prefers-reduced-motion: reduce)') changeListeners.push(listener as () => void)
      },
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }))

    render(<ThemeProvider><MotionTokenProbe /></ThemeProvider>)
    expect(screen.getByTestId('motion-token')).toHaveTextContent('false')

    act(() => {
      matches = false
      changeListeners.forEach((listener) => listener())
    })
    expect(screen.getByTestId('motion-token')).toHaveTextContent('true')
  })

  it('uses the legacy MediaQueryList listener supported by older WebView2', () => {
    const addListener = vi.fn()
    const removeListener = vi.fn()
    vi.spyOn(window, 'matchMedia').mockImplementation((query) => ({
      matches: true,
      media: query,
      onchange: null,
      addEventListener: undefined,
      removeEventListener: undefined,
      addListener,
      removeListener,
      dispatchEvent: vi.fn(),
    } as unknown as MediaQueryList))

    const view = render(<ThemeProvider><MotionTokenProbe /></ThemeProvider>)
    expect(addListener).toHaveBeenCalledOnce()
    view.unmount()
    expect(removeListener).toHaveBeenCalledOnce()
  })
})
