import { describe, expect, it } from 'vitest'

import { DEFAULT_CLI_ARGS } from '../features/localModels/settingsModelOptions'

describe('local CLI default arguments', () => {
  it('never suggests bypass, yolo, trust, or auto-approval flags', () => {
    const defaults = Object.values(DEFAULT_CLI_ARGS).join(' ').toLowerCase()

    expect(defaults).not.toContain('bypasspermissions')
    expect(defaults).not.toContain('dangerously-bypass')
    expect(defaults).not.toContain('dangerously-skip')
    expect(defaults).not.toContain('--approve-mcps')
    expect(defaults).not.toContain('--trust')
    expect(defaults).not.toContain('--yolo')
    expect(defaults).not.toContain('"--auto"')
  })
})
