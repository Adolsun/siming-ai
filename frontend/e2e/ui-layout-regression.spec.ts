import { expect, test, type Page, type Route } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

const model = {
  id: 'opencode-ready',
  provider: 'opencode_cli',
  default_model: 'opencode/deepseek-v4-flash-free',
  is_global_default: true,
  readiness_status: 'ready',
  readiness_message: '真实对话已通过',
  is_usable: true,
  provider_type: 'local_cli',
}

const project = {
  id: 'p1',
  title: '海滨城记忆修复档案',
  description: '算法分配记忆的近未来悬疑故事',
  created_at: '2026-07-20T08:00:00Z',
  updated_at: '2026-07-27T08:00:00Z',
}

const outlineNodes = [
  {
    id: 'volume-1', project_id: 'p1', parent_id: null, node_type: 'volume', title: '第一卷 被城市共同遗忘的火灾',
    summary: '林岚收到来自未来的死亡通知。', status: 'in_progress', sort_order: 0, linked_characters: [],
    created_at: '2026-07-20T08:00:00Z', updated_at: '2026-07-27T08:00:00Z',
    children: [
      {
        id: 'outline-1', project_id: 'p1', parent_id: 'volume-1', node_type: 'chapter', title: '第一章 来自三天后的死亡通知',
        summary: '档案修复师林岚发现通知中的死亡地点不存在。', status: 'completed', sort_order: 0, linked_characters: [],
        created_at: '2026-07-20T08:00:00Z', updated_at: '2026-07-27T08:00:00Z', children: [],
      },
      {
        id: 'outline-2', project_id: 'p1', parent_id: 'volume-1', node_type: 'chapter', title: '第二章 被删掉的集体记忆留下潮汐般的回声',
        summary: '林岚在旧档案中发现全城共同经历过一场火灾。', status: 'in_progress', sort_order: 1, linked_characters: [],
        created_at: '2026-07-20T08:00:00Z', updated_at: '2026-07-27T08:00:00Z', children: [],
      },
    ],
  },
]

const flatOutline = [outlineNodes[0], ...outlineNodes[0].children]

const chapters = [
  {
    id: 'chapter-1', project_id: 'p1', outline_node_id: 'outline-1',
    title: '第一章 来自三天后的死亡通知与一座不存在的旧港档案馆', word_count: 2186, current_version: 3,
    outline_title: '第一章 来自三天后的死亡通知', outline_status: 'completed', outline_node_type: 'chapter',
    outline_path: ['第一卷 被城市共同遗忘的火灾', '第一章 来自三天后的死亡通知'],
    summary_text: '林岚收到死亡通知，并在通知的校验码中发现被删除的火灾档案索引。',
    key_events: ['未来死亡通知', '旧港档案馆', '火灾索引'],
    created_at: '2026-07-20T08:00:00Z', updated_at: '2026-07-27T08:00:00Z',
  },
  {
    id: 'chapter-2', project_id: 'p1', outline_node_id: 'outline-2',
    title: '第二章 潮汐退去以后所有人都忘记了那场火', word_count: 2042, current_version: 2,
    outline_title: '第二章 被删掉的集体记忆', outline_status: 'in_progress', outline_node_type: 'chapter',
    outline_path: ['第一卷 被城市共同遗忘的火灾', '第二章 被删掉的集体记忆'],
    created_at: '2026-07-20T08:00:00Z', updated_at: '2026-07-27T08:00:00Z',
  },
]

const operations = [
  {
    id: 'review-new', source_id: 'session-1', source_kind: 'novel_creation', project_id: 'p1', title: '新书立项 · 最终审阅',
    status: 'waiting_user', health_status: 'active', phase: 'final_review', current_message: '最终审阅已经保存，等待你的确认',
    progress: { mode: 'indeterminate' }, model_source: 'opencode_cli:opencode/deepseek-v4-flash-free',
    outcome: 'waiting_user', result_summary: '立项内容已经生成', result: { outcome: 'waiting_user', summary: '立项内容已经生成' },
    attention: { kind: 'confirmation', title: '最终内容等待确认', message: '请审阅后创建正式作品。', action_label: '前往审阅', action_url: '/novel-creation?session=session-1&stage=final_review' },
    resume_url: '/novel-creation?session=session-1', can_pause: false, can_cancel: true, can_retry: false,
    elapsed_seconds: 5400, last_activity_at: '2026-07-25T08:00:00Z', created_at: '2026-07-25T06:00:00Z', updated_at: '2026-07-25T08:00:00Z',
  },
  {
    id: 'review-old', source_id: 'session-1', source_kind: 'novel_creation', project_id: 'p1', title: '新书立项 · 最终审阅',
    status: 'failed', health_status: 'stalled', phase: 'final_review', current_message: '上一次尝试未完成', progress: { mode: 'indeterminate' },
    can_pause: false, can_cancel: false, can_retry: false, elapsed_seconds: 300,
    created_at: '2026-07-24T06:00:00Z', updated_at: '2026-07-24T06:05:00Z',
  },
  {
    id: 'archive-1', source_id: 'chapter-1', source_kind: 'cataloging', project_id: 'p1', title: '作品建档 · 第一章',
    status: 'running', health_status: 'active', phase: 'chapter_archive', current_message: '正在提取角色状态与伏笔',
    progress: { mode: 'determinate', current: 2, total: 5, percent: 40 }, can_pause: true, can_cancel: true, can_retry: false,
    elapsed_seconds: 68, last_activity_at: '2026-07-27T09:59:30Z', created_at: '2026-07-27T09:58:52Z', updated_at: '2026-07-27T09:59:30Z',
  },
]

async function fulfill(route: Route, data: unknown, status = 200) {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) })
}

async function mockUiApi(page: Page) {
  await page.clock.setFixedTime(new Date('2026-07-27T10:00:00Z'))
  await page.addInitScript(() => {
    class MockEventSource {
      static readonly CONNECTING = 0
      static readonly OPEN = 1
      static readonly CLOSED = 2
      readonly url: string
      readyState = MockEventSource.OPEN
      onopen: ((event: Event) => void) | null = null
      onerror: ((event: Event) => void) | null = null
      constructor(url: string | URL) { this.url = String(url) }
      addEventListener() {}
      removeEventListener() {}
      dispatchEvent() { return true }
      close() { this.readyState = MockEventSource.CLOSED }
    }
    Object.defineProperty(window, 'EventSource', { configurable: true, value: MockEventSource })
  })

  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/v1/config/getting-started') {
      return fulfill(route, { code: 0, data: {
        free_models: [], recommended_model: null, platform_supported: true, configured: true,
        configured_model: model.default_model, is_global_default: true, needs_setup: false,
        has_detected_models: true, has_usable_models: true,
        global_model: { provider: model.provider, model: model.default_model }, activation_job: null,
      } })
    }
    if (path === '/api/v1/config/models') return fulfill(route, { code: 0, data: { items: [model], total: 1 } })
    if (path === '/api/v1/config/global-model') return fulfill(route, { code: 0, data: { provider: model.provider, model: model.default_model } })
    if (path === '/api/v1/config/content-root') return fulfill(route, { code: 0, data: { current_path: 'D:/Siming', default_path: 'D:/Siming', is_default: true, exists: true, is_empty: false, looks_like_siming_root: true } })
    if (path === '/api/v1/config/launcher') return fulfill(route, { code: 0, data: { launch_mode: 'desktop', update_channel: 'stable', restart_required: false } })
    if (path === '/api/v1/operations') return fulfill(route, { code: 0, data: { items: operations } })
    if (path === '/api/v1/projects/p1') return fulfill(route, { code: 0, data: project })
    if (path === '/api/v1/projects/p1/chapters') return fulfill(route, { code: 0, data: { items: chapters, total: chapters.length } })
    if (path === '/api/v1/projects/p1/chapters/chapter-1') return fulfill(route, { code: 0, data: { ...chapters[0], content: '海风把死亡通知吹得贴在修复台上。\n\n林岚第一次看见自己的名字出现在三天后的死亡档案里。', snapshot_count: 2 } })
    if (path === '/api/v1/projects/p1/chapters/chapter-1/snapshots') return fulfill(route, { code: 0, data: { items: [
      { id: 'snapshot-2', chapter_id: 'chapter-1', version_number: 3, word_count: 2186, trigger_type: 'manual_save', created_at: '2026-07-27T08:00:00Z' },
      { id: 'snapshot-1', chapter_id: 'chapter-1', version_number: 2, word_count: 2040, trigger_type: 'ai_insert', created_at: '2026-07-26T08:00:00Z' },
    ], total: 2 } })
    if (path === '/api/v1/projects/p1/outline') return fulfill(route, { code: 0, data: { items: outlineNodes, flat: flatOutline, total: flatOutline.length } })
    if (path === '/api/v1/projects/p1/characters') return fulfill(route, { code: 0, data: { items: [{ id: 'character-1', name: '林岚', role_type: 'protagonist', current_version: 2, is_evolution_tracked: true }], total: 1 } })
    if (path === '/api/v1/projects/p1/narrative-governance') return fulfill(route, { code: 0, data: {
      foreshadowings: [], causal_edges: [], narrative_debts: [], character_states: [], quality_metrics: [], checkpoints: [],
      counts: { open_foreshadowings: 0, open_causal_edges: 0, open_debts: 0 },
    } })
    return fulfill(route, { code: 0, data: {} })
  })
}

async function expectViewportSafe(page: Page) {
  const overflow = await page.evaluate(() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(1)
  const clippedControls = await page.evaluate(() => Array.from(document.querySelectorAll<HTMLElement>('button, input, textarea, [role="button"]'))
    .filter((element) => {
      const style = getComputedStyle(element)
      if (style.display === 'none' || style.visibility === 'hidden') return false
      const rect = element.getBoundingClientRect()
      const intersectsViewport = rect.right > 0 && rect.left < window.innerWidth && rect.bottom > 0 && rect.top < window.innerHeight
      return intersectsViewport && rect.width > 0 && rect.height > 0 && (rect.left < -1 || rect.right > window.innerWidth + 1)
    })
    .map((element) => element.getAttribute('aria-label') || element.textContent?.trim().slice(0, 40)))
  expect(clippedControls).toEqual([])
}

async function expectNoSeriousAccessibilityViolations(page: Page) {
  const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze()
  expect(result.violations.filter((item) => ['serious', 'critical'].includes(item.impact || ''))).toEqual([])
}

async function expectVisualSnapshot(page: Page, name: string) {
  if (!process.env.CI) {
    await expect(page).toHaveScreenshot(name, { animations: 'disabled' })
  }
}

const viewports = [
  { name: '1920x1080', width: 1920, height: 1080 },
  { name: '1400x900', width: 1400, height: 900 },
  { name: '1280x720', width: 1280, height: 720 },
  { name: '800x600', width: 800, height: 600 },
]

for (const viewport of viewports) {
  test(`keeps core writing views usable at ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize(viewport)
    await mockUiApi(page)

    await page.goto('/project/p1', { waitUntil: 'networkidle' })
    await expect(page.locator('.writer-editor-title')).toContainText('第一章 来自三天后的死亡通知')
    await expect(page.getByText('已完成', { exact: true }).first()).toBeVisible()
    await expectViewportSafe(page)
    await expectVisualSnapshot(page, `writer-${viewport.name}.png`)

    await page.goto('/project/p1?view=outline', { waitUntil: 'networkidle' })
    await expect(page.getByLabel('搜索大纲')).toBeVisible()
    await expectViewportSafe(page)
    await expectVisualSnapshot(page, `outline-${viewport.name}.png`)

    await page.getByRole('button', { name: /任务中心/ }).click()
    await expect(page.getByRole('heading', { name: /待你处理/ })).toBeVisible()
    await expect(page.getByText('历史尝试 1')).toBeVisible()
    await expect(page.locator('.ant-drawer-content-wrapper')).toHaveCSS('transform', 'none')
    await expectViewportSafe(page)
    await expectVisualSnapshot(page, `task-center-${viewport.name}.png`)

    if (viewport.width === 1920 || viewport.width === 800) await expectNoSeriousAccessibilityViolations(page)
  })
}

test('keeps onboarding, model settings and governance visually focused', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 })
  await mockUiApi(page)

  await page.goto('/getting-started', { waitUntil: 'networkidle' })
  await expect(page.getByRole('heading', { name: '免费写作能力已经准备好' })).toBeVisible()
  await expectViewportSafe(page)
  await expectVisualSnapshot(page, 'quick-start-ready-1920x1080.png')

  await page.goto('/settings', { waitUntil: 'networkidle' })
  await expect(page.getByText('AI 已准备好')).toBeVisible()
  await expectViewportSafe(page)
  await expectVisualSnapshot(page, 'model-settings-1920x1080.png')

  await page.goto('/project/p1?view=governance', { waitUntil: 'networkidle' })
  await expect(page.getByText('还没有可治理的叙事记录')).toBeVisible()
  await expectViewportSafe(page)
  await expectVisualSnapshot(page, 'governance-empty-1920x1080.png')
  await expectNoSeriousAccessibilityViolations(page)
})
