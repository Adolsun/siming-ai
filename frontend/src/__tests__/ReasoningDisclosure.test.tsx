import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ReasoningDisclosure } from '../components/assistant/ReasoningDisclosure'

describe('model API reasoning display', () => {
  it('renders a large received chunk immediately and preserves the author collapse choice', () => {
    const content = '模型返回的可见内容。'.repeat(2000)
    const view = render(<ReasoningDisclosure content={content} streaming />)
    const button = screen.getByRole('button', { name: /模型思考摘要/ })
    expect(view.container.querySelector('.assistant-reasoning-text')?.textContent).toBe(content)
    expect(button).toHaveAttribute('aria-expanded', 'true')
    fireEvent.click(button)
    view.rerender(<ReasoningDisclosure content={`${content}下一段。`} streaming />)
    expect(button).toHaveAttribute('aria-expanded', 'false')
    view.rerender(<ReasoningDisclosure content={content} streaming={false} />)
    expect(view.container.querySelector('.assistant-reasoning-caret')).toBeNull()
    expect(button).toHaveAccessibleName(/已完成/)
  })
})
