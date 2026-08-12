import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
}))

vi.mock('../api/client', () => ({ apiClient: api }))

import CreationBriefPage from '../pages/CreationBriefPage'

const context = {
  revision: 7,
  constraints: {
    brief: '用实验挑战宗族修炼秩序',
    genre: '东方玄幻',
    target_audience: '成年大众',
    platform: '起点中文网',
    target_words: 2_500_000,
    target_chapters: 1_000,
    world_tone: '家族权谋与修炼实验并行',
    story_structure: '成长与求真双线',
    pacing: '三章一验证',
    writing_style: '克制冷峻，以动作推进',
    special_requirements: ['信息必须跨章一致'],
    avoid: ['临时增加无铺垫能力'],
  },
  creative_direction: {
    selected_concept_id: 'concept-1',
    selected: {
      id: 'concept-1',
      title: '经脉迷局',
      logline: '穿越者以现代实验方法破解家族修炼体系。',
      core_conflict: '求真与宗族秩序冲突',
    },
  },
  world_style: {
    writing_style: '克制冷峻，以动作推进',
    narrative_perspective: '第三人称限知',
    style_rules: ['少解释，多可验证细节'],
    forbidden_patterns: ['不要替人物总结情绪'],
  },
  artifact_statuses: {
    constraints: 'confirmed',
    concepts: 'confirmed',
    world_style: 'confirmed',
  },
}

const response = <T,>(data: T) => ({ data: { code: 0, message: 'ok', data } })

describe('CreationBriefPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.get.mockResolvedValue(response({
      session: { id: 'session-1', revision: 7 },
      context,
    }))
    api.patch.mockResolvedValue(response({
      project_id: 'project-1',
      creation_session_id: 'session-1',
      revision: 10,
      changed_artifacts: ['constraints', 'concepts', 'world_style'],
      creation: { ...context, revision: 10 },
    }))
  })

  it('exposes constraints, creative direction and style and saves one authoritative revision', async () => {
    render(<CreationBriefPage projectId="project-1" />)

    expect(await screen.findByRole('heading', { name: '创作设定' })).toBeInTheDocument()
    expect(screen.getByDisplayValue('2500000')).toBeInTheDocument()
    expect(screen.getByDisplayValue('经脉迷局')).toBeInTheDocument()
    expect(screen.getAllByDisplayValue('克制冷峻，以动作推进').length).toBeGreaterThan(0)

    fireEvent.change(screen.getByRole('spinbutton', { name: '目标字数' }), {
      target: { value: '2600000' },
    })
    fireEvent.change(screen.getByLabelText('正文风格总则'), {
      target: { value: '冷峻克制，关键转折只用动作呈现' },
    })
    fireEvent.click(screen.getByRole('button', { name: /保存创作设定/ }))

    await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(1))
    expect(api.patch).toHaveBeenCalledWith(
      '/projects/project-1/creation-brief',
      expect.objectContaining({
        expected_revision: 7,
        constraints: expect.objectContaining({
          target_words: 2_600_000,
          target_chapters: 1_000,
          writing_style: '冷峻克制，关键转折只用动作呈现',
        }),
        creative_direction: {
          selected: expect.objectContaining({ title: '经脉迷局' }),
        },
        world_style: expect.objectContaining({
          writing_style: '冷峻克制，关键转折只用动作呈现',
        }),
      }),
    )
  })

  it('lets an imported project establish editable creation settings explicitly', async () => {
    api.get.mockResolvedValueOnce(response({ session: null, context: null }))
    api.post.mockResolvedValueOnce(response({
      session: { id: 'session-imported', revision: 0 },
      context: { ...context, revision: 0 },
    }))

    render(<CreationBriefPage projectId="project-imported" />)

    const initialize = await screen.findByRole('button', { name: /建立创作设定/ })
    fireEvent.click(initialize)

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/projects/project-imported/creation-brief/ensure',
    ))
    expect(await screen.findByDisplayValue('经脉迷局')).toBeInTheDocument()
  })
})
