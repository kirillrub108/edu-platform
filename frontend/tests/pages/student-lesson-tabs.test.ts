/**
 * Guards the student lesson view's tabbed layout.
 *
 * Same constraint as teacher-lesson-comments.test.ts: there is no component-mount
 * harness here (@vue/test-utils isn't a dependency and npm is banned), so these
 * assert that the view source wires the tab interface up the same way the teacher
 * page does — UiTabs + query-driven ?tab, three accessible tab panels, status
 * badges, and a single repositioned CommentsPanel.
 *
 * The page body lives in components/student/LessonView.vue (shared between the
 * student page and the teacher preview); the page itself is a thin wrapper.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

// vitest runs with the frontend project root as cwd.
const studentLessonPage = resolve(
  process.cwd(),
  'src/pages/student/courses/[courseId]/lessons/[lessonId].vue',
)
const lessonView = resolve(process.cwd(), 'src/components/student/LessonView.vue')
const uiTabs = resolve(process.cwd(), 'src/components/UiTabs.vue')

describe('student lesson page wrapper', () => {
  const source = readFileSync(studentLessonPage, 'utf-8')

  it('renders the shared LessonView without the preview flag', () => {
    expect(source).toMatch(/<StudentLessonView[^>]*:lesson-id="lessonId"/)
    expect(source).not.toContain(' preview')
  })
})

describe('student lesson view tabs', () => {
  const source = readFileSync(lessonView, 'utf-8')

  it('renders the shared UiTabs with the three lesson tabs', () => {
    expect(source).toContain('<UiTabs')
    expect(source).toMatch(/id: 'lesson', label: 'Урок'/)
    expect(source).toMatch(/id: 'quiz', label: 'Тест'/)
    expect(source).toMatch(/id: 'assignments', label: 'Задания'/)
  })

  it('drives the active tab from the URL query like the teacher page', () => {
    expect(source).toContain('route.query.tab')
    expect(source).toContain("router.replace({ query: { ...route.query, tab: id } })")
  })

  it('exposes one accessible tab panel per tab', () => {
    for (const id of ['lesson', 'quiz', 'assignments']) {
      expect(source).toContain(`id="tabpanel-${id}"`)
      expect(source).toContain(`aria-labelledby="tab-${id}"`)
    }
    expect(source.match(/role="tabpanel"/g)?.length).toBe(3)
  })

  it('keeps the panels mounted across switches with v-show', () => {
    expect(source).toContain("v-show=\"activeTab === 'lesson'\"")
    expect(source).toContain("v-show=\"activeTab === 'quiz'\"")
    expect(source).toContain("v-show=\"activeTab === 'assignments'\"")
  })

  it('feeds status badges into the tabs', () => {
    expect(source).toContain('lessonBadge')
    expect(source).toContain('quizBadge')
    expect(source).toContain('assignmentBadge')
    expect(source).toMatch(/badge: lessonBadge\.value/)
  })

  it('mounts a single CommentsPanel and a mobile drawer toggle', () => {
    expect(source.match(/<CommentsPanel/g)?.length).toBe(1)
    expect(source).toMatch(/<CommentsPanel[^>]*:lesson-id="lessonId"/)
    expect(source).toContain('commentsOpen')
    expect(source).toContain('commentsTotal')
  })
})

describe('UiTabs badge support', () => {
  const source = readFileSync(uiTabs, 'utf-8')

  it('renders an optional badge after the tab label', () => {
    expect(source).toContain('tab.badge')
    expect(source).toContain('badge?:')
  })
})
