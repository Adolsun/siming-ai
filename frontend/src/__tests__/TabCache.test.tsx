import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { expect, it } from 'vitest'
import TabCache from '../components/TabCache'

function Draft({ target, active }: { target: string; active: boolean }) {
  const [text, setText] = useState('未保存正文')
  return <><input aria-label="草稿" value={text} onChange={event => setText(event.target.value)} /><output>{target}:{String(active)}</output></>
}

it('updates cached route props and visibility without discarding an unsaved draft', () => {
  const tabs = (target: string, active: boolean) => ({
    writer: () => <Draft target={target} active={active} />,
    cataloging: () => <div>建档页面</div>,
  })
  const view = render(<TabCache activeKey="writer" tabs={tabs('job-a', true)} />)
  fireEvent.change(screen.getByRole('textbox', { name: '草稿' }), { target: { value: '作者正在编辑' } })
  view.rerender(<TabCache activeKey="cataloging" tabs={tabs('job-b', false)} />)
  expect(screen.getByText('job-b:false')).toBeInTheDocument()
  view.rerender(<TabCache activeKey="writer" tabs={tabs('job-c', true)} />)
  expect(screen.getByRole('textbox', { name: '草稿' })).toHaveValue('作者正在编辑')
  expect(screen.getByText('job-c:true')).toBeInTheDocument()
})
