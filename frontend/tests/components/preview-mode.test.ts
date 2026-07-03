/**
 * Guards for the teacher «view as student» preview wiring. No component-mount
 * harness exists here (@vue/test-utils isn't a dependency and npm is banned),
 * so this asserts the source (same approach as course-card-publish.test.ts):
 * the effective-visibility badge, the disabled submission form, and QuizTaker's
 * dry-run composable switch.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const read = (rel: string) => readFileSync(resolve(process.cwd(), rel), 'utf-8')
const layout = read('src/layouts/student.vue')
const submit = read('src/components/assignments/Submit.vue')
const panel = read('src/components/assignments/StudentPanel.vue')
const quizTaker = read('src/components/QuizTaker.vue')
const lessonView = read('src/components/student/LessonView.vue')

describe('effective-visibility badge («Студент не увидит»)', () => {
  it('layout derives hidden from visible_to_student for modules and lessons', () => {
    expect(layout).toMatch(/hidden:\s*!m\.visible_to_student/)
    expect(layout).toMatch(/hidden:\s*!l\.visible_to_student/)
  })

  it('layout badges and dims hidden nodes', () => {
    expect(layout).toMatch(/v-if="mod\.hidden"/)
    expect(layout).toMatch(/v-if="lesson\.hidden"/)
    expect(layout).toMatch(/lesson\.hidden && 'opacity-50'/)
    expect((layout.match(/Студент не увидит/g) ?? []).length).toBeGreaterThanOrEqual(2)
  })

  it('lesson view badges the currently opened hidden lesson', () => {
    expect(lessonView).toMatch(/visible_to_student === false/)
    expect(lessonView).toContain('Студент не увидит')
  })
})

describe('preview banner and exit', () => {
  it('layout shows a non-dismissable banner with an exit button', () => {
    expect(layout).toContain('Режим предпросмотра')
    expect(layout).toContain('Выйти из предпросмотра')
    expect(layout).toMatch(/@click="exitPreview"/)
    expect(layout).toMatch(/previewStore\.reset\(\)/)
  })

  it('layout warns when the course itself is unpublished', () => {
    expect(layout).toMatch(/!previewStore\.course\.is_published/)
    expect(layout).toContain('Курс не опубликован')
  })
})

describe('assignment submission is disabled in preview', () => {
  it('Submit disables draft/submit/upload with the preview tooltip', () => {
    expect(submit).toContain("const PREVIEW_TOOLTIP = 'Недоступно в предпросмотре'")
    expect(submit).toMatch(/:disabled="preview \|\| \(isSubmitted && !hasChanges\)"/)
    expect(submit).toMatch(/:disabled="preview \|\| !canSubmit/)
    expect(submit).toMatch(/:disabled="preview \|\| submissionFiles\.length/)
    expect((submit.match(/preview \? PREVIEW_TOOLTIP : undefined/g) ?? []).length).toBe(3)
  })

  it('Submit handlers hard-return in preview (no writes even if re-enabled)', () => {
    expect((submit.match(/if \(props\.preview\) return/g) ?? []).length).toBe(3)
  })

  it('StudentPanel fetches the owner list in preview and badges drafts', () => {
    expect(panel).toMatch(/preview \? store\.teacherState/)
    expect(panel).toMatch(/if \(props\.preview\) void store\.fetchTeacher\(id\)/)
    expect(panel).toMatch(/a\.status === 'draft'/)
    expect(panel).toContain('Студент не увидит')
  })
})

describe('quiz dry-run', () => {
  it('QuizTaker switches to useQuizPreview and skips the attempts endpoint', () => {
    expect(quizTaker).toMatch(/props\.preview \? useQuizPreview\(lessonIdRef\) : null/)
    expect(quizTaker).toMatch(/if \(props\.preview\) return \/\/ dry-run/)
  })

  it('preview submit button reads «Проверить»', () => {
    expect(quizTaker).toMatch(/preview \? 'Проверить' : 'Отправить ответы'/)
  })
})
