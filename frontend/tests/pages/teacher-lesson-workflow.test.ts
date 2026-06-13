/**
 * Guards the teacher lesson "Урок" tab wizard + sticky comments redesign.
 *
 * Same constraint as the sibling page tests: no component-mount harness exists
 * (@vue/test-utils isn't a dependency and npm is banned), so these assert the
 * page source wires the wizard up — step nav, v-show step panels (panels must
 * stay mounted so polling/snapshot refs survive switches), and a single
 * CommentsPanel moved into the shared sticky column.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const teacherLessonPage = resolve(process.cwd(), 'src/pages/lessons/[id]/index.vue')
const workflowNav = resolve(process.cwd(), 'src/components/lesson/WorkflowNav.vue')

describe('teacher lesson workflow wizard', () => {
  const source = readFileSync(teacherLessonPage, 'utf-8')

  it('drives the Урок tab as a step wizard', () => {
    expect(source).toContain('type StepKey')
    expect(source).toContain('const workflowSteps')
    expect(source).toContain('const activeStep')
    expect(source).toContain('const pickInitialStep')
  })

  it('renders the step navigator for both desktop and mobile', () => {
    expect(source.match(/<LessonWorkflowNav/g)?.length).toBe(2)
    expect(source).toContain('orientation="vertical"')
    expect(source).toContain('orientation="horizontal"')
  })

  it('keeps every step panel mounted via v-show (no remount of polling panels)', () => {
    for (const key of ['mode', 'video', 'presentation', 'script', 'generate', 'history']) {
      expect(source).toContain(`v-show="activeStep === '${key}'"`)
    }
    // The vision snapshot ref must stay mounted across step switches.
    expect(source).toMatch(/ref="visionPanelRef"/)
  })

  it('moves a single CommentsPanel into the shared sticky column with a mobile drawer', () => {
    expect(source.match(/<CommentsPanel/g)?.length).toBe(1)
    expect(source).toMatch(/<CommentsPanel[^>]*:lesson-id="lessonId"/)
    expect(source).toContain('commentsOpen')
    expect(source).toContain('commentsTotal')
  })

  it('makes the tab bar sticky', () => {
    expect(source).toMatch(/sticky top-16[^"]*"[\s\S]*?<UiTabs/)
  })
})

describe('LessonWorkflowNav', () => {
  const source = readFileSync(workflowNav, 'utf-8')

  it('is an accessible, controllable step list', () => {
    expect(source).toContain('aria-current')
    expect(source).toContain("'update:modelValue'")
    expect(source).toContain('orientation')
  })
})
