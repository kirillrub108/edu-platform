/**
 * Guard for the draft-reminder toast wiring. No component-mount harness exists
 * here (@vue/test-utils isn't a dependency and npm is banned), so this asserts
 * the source: the action reads "Опубликовать" (not the old "Показать") and is
 * bound to the handler that navigates back to the course editor. The once-per-
 * session behavior itself is covered by tests/stores/courseEditor.test.ts.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const toast = readFileSync(
  resolve(process.cwd(), 'src/components/DraftReminderToast.vue'),
  'utf-8',
)

describe('DraftReminderToast', () => {
  it('labels the action "Опубликовать" and drops the old "Показать"', () => {
    expect(toast).toContain('Опубликовать')
    expect(toast).not.toContain('Показать')
  })

  it('the action navigates to the course editor and dismisses the toast', () => {
    expect(toast).toMatch(/@click="goToCourse"/)
    expect(toast).toMatch(/navigateTo\(`\/courses\/\$\{courseId\}`\)/)
    expect(toast).toContain('store.dismissDraftToast()')
  })

  it('only renders while a draft toast is queued', () => {
    expect(toast).toMatch(/v-if="draftToast"/)
  })
})
