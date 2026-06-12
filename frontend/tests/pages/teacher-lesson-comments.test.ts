/**
 * Regression guard for the "teacher can't see comments" bug.
 *
 * The comments store + CommentsPanel are role-agnostic and the backend already
 * returns every comment to the lesson's teacher-owner; the defect was that the
 * teacher lesson page never mounted CommentsPanel, so no request was ever made.
 *
 * No component-mount harness exists here (@vue/test-utils isn't a dependency and
 * npm is banned), so this asserts the page source wires the panel up, mirroring
 * how the student lesson page does.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

// vitest runs with the frontend project root as cwd.
const teacherLessonPage = resolve(
  process.cwd(),
  'src/pages/lessons/[id]/index.vue',
)

describe('teacher lesson page comments', () => {
  const source = readFileSync(teacherLessonPage, 'utf-8')

  it('mounts CommentsPanel for the current lesson', () => {
    expect(source).toContain('<CommentsPanel')
    expect(source).toMatch(/<CommentsPanel[^>]*:lesson-id="lessonId"/)
  })

  it('passes a can-delete predicate so the teacher can moderate', () => {
    expect(source).toMatch(/<CommentsPanel[^>]*:can-delete="canDeleteComment"/)
    expect(source).toContain('const canDeleteComment')
  })
})
