/**
 * Guard for the dashboard course-card publish action. No component-mount harness
 * exists here (@vue/test-utils isn't a dependency and npm is banned), so this
 * asserts the source: the card exposes a publish toggle (only with showActions)
 * and the dashboard wires it to a handler that toggles via /publish and moves the
 * card between the published/drafts sections.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const read = (rel: string) => readFileSync(resolve(process.cwd(), rel), 'utf-8')
const card = read('src/components/CourseCard.vue')
const dashboard = read('src/pages/dashboard.vue')

describe('CourseCard publish action', () => {
  it('emits "publish" and labels the toggle by is_published', () => {
    expect(card).toMatch(/\(e: 'publish', id: string\): void/)
    expect(card).toMatch(/@click\.stop\.prevent="onPublishToggle"/)
    expect(card).toContain("emit('publish', props.course.id)")
    expect(card).toContain('Опубликовать')
    expect(card).toContain('Снять с публикации')
  })

  it('only renders the toggle when actions are enabled', () => {
    expect(card).toMatch(/v-else-if="showActions"/)
  })
})

describe('dashboard publish handler', () => {
  it('wires @publish to publishCourse', () => {
    expect(dashboard).toMatch(/@publish="publishCourse"/)
    expect(dashboard).toContain('const publishCourse')
  })

  it('toggles via the publish endpoint and re-buckets the card', () => {
    expect(dashboard).toMatch(/\/courses\/\$\{id\}\/publish`,\s*\{\s*method:\s*'PUT'\s*\}/)
    expect(dashboard).toMatch(/updated\.is_published \? groups\.published : groups\.drafts/)
  })
})
