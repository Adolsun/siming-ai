import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import SystemNav from '../components/SystemNav'

describe('SystemNav', () => {
  beforeEach(() => vi.clearAllMocks())

  it('keeps quick start as a first-level entry after AI is ready', () => {
    render(<MemoryRouter initialEntries={['/dashboard']}><SystemNav current="dashboard" /></MemoryRouter>)

    expect(screen.getByRole('button', { name: '快速开始' })).toBeInTheDocument()
  })

  it('marks quick start as the current page', () => {
    render(<MemoryRouter initialEntries={['/dashboard']}><SystemNav current="dashboard" /></MemoryRouter>)

    expect(screen.getByRole('button', { name: '作品库' })).toHaveAttribute('aria-current', 'page')
  })
})
