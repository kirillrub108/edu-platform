/**
 * courseEditor store: the draft-leave reminder fires at most once per session
 * and only when there is unpublished content. Mirrors billing.test.ts setup
 * (resetModules + dynamic Pinia import; ref stubbed as a global auto-import).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

const loadStore = async () => {
  const { createPinia, setActivePinia } = await import('pinia')
  setActivePinia(createPinia())
  const { useCourseEditorStore } = await import('../../src/stores/courseEditor')
  return useCourseEditorStore()
}

beforeEach(() => {
  vi.resetModules()
  vi.stubGlobal('ref', ref)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('useCourseEditorStore', () => {
  it('не показывает тост, если нет неопубликованного контента', async () => {
    const store = await loadStore()
    store.maybeShowDraftReminder('c1', false)
    expect(store.draftToast).toBeNull()
    expect(store.draftReminderShown).toBe(false)
  })

  it('показывает тост один раз за сессию при наличии черновиков', async () => {
    const store = await loadStore()

    store.maybeShowDraftReminder('c1', true)
    expect(store.draftToast).toEqual({ courseId: 'c1' })
    expect(store.draftReminderShown).toBe(true)

    // Dismiss, then leave again in the same session → stays silent.
    store.dismissDraftToast()
    expect(store.draftToast).toBeNull()

    store.maybeShowDraftReminder('c2', true)
    expect(store.draftToast).toBeNull()
  })
})
