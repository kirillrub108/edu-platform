/**
 * Guards the regenerate/autosave race fix in SlideTextEditor. Same constraint as
 * the other component guards here (no @vue/test-utils, npm is banned), so this
 * asserts the source directly.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const src = readFileSync(
  resolve(process.cwd(), 'src/components/SlideTextEditor.vue'),
  'utf-8',
)

describe('SlideTextEditor regen/autosave write ordering', () => {
  it('gates both persistCurrent and regenerate writes behind a per-slide ticket', () => {
    expect(src).toMatch(/const ticket = beginWrite\(slide\.id\)/g)
    expect(src.match(/const ticket = beginWrite\(slide\.id\)/g)?.length).toBe(2)
    expect(src.match(/isLatestWrite\(slide\.id, ticket\)/g)?.length).toBe(2)
  })

  it('does not let a repeat click fire a second regenerate request for the same slide', () => {
    expect(src).toMatch(/if \(regenIds\.value\.has\(slide\.id\)\) return/)
  })

  it('does not abort an in-flight regen just because the viewed slide changed', () => {
    const watchBlock = src.match(/watch\(currentIdx, \(\) => \{[\s\S]*?\}\)/)?.[0] ?? ''
    expect(watchBlock).not.toContain('regenController')
    expect(watchBlock).toContain('pendingRegen.value = null')
  })

  it('stashes a fresh regeneration instead of clobbering an unsaved draft', () => {
    expect(src).toMatch(/if \(buffer\.value === previousText\.value\) \{/)
    expect(src).toContain('pendingRegen.value = { slideId: slide.id, text:')
  })

  it('applying a pending regen keeps the draft revertable', () => {
    expect(src).toMatch(/const applyPendingRegen = \(\) => \{[\s\S]*?previousText\.value = buffer\.value[\s\S]*?canRevert\.value = true/)
  })
})
