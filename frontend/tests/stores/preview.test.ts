/**
 * Preview store: owner-annotated course tree + strictly local (dry-run)
 * completion state. Mirrors assignments.test.ts: resetModules + dynamic
 * import, Nuxt auto-imports stubbed as globals.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { computed, ref } from 'vue'

const fetchMock = vi.fn()

const loadStore = async () => {
  const { createPinia, setActivePinia } = await import('pinia')
  setActivePinia(createPinia())
  const mod = await import('../../src/stores/preview')
  return mod.usePreviewStore()
}

beforeEach(() => {
  vi.resetModules()
  fetchMock.mockReset()
  vi.stubGlobal('ref', ref)
  vi.stubGlobal('computed', computed)
  vi.stubGlobal('useApi', () => ({ apiFetch: fetchMock }))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

// Published lesson inside a DRAFT module: backend annotates it with
// visible_to_student=false (effective visibility) — the badge source.
const tree = {
  id: 'c1',
  title: 'Курс',
  description: null,
  is_published: false,
  modules: [
    {
      id: 'm1',
      title: 'Опубликованный модуль',
      order: 0,
      is_published: true,
      visible_to_student: true,
      lessons: [
        { id: 'l1', title: 'Виден', order: 0, content_type: 'video', status: 'published', is_published: true, visible_to_student: true },
        { id: 'l2', title: 'Черновик', order: 1, content_type: 'text', status: 'draft', is_published: false, visible_to_student: false },
      ],
    },
    {
      id: 'm2',
      title: 'Черновик-модуль',
      order: 1,
      is_published: false,
      visible_to_student: false,
      lessons: [
        { id: 'l3', title: 'Published в draft-модуле', order: 0, content_type: 'video', status: 'published', is_published: true, visible_to_student: false },
      ],
    },
  ],
}

describe('fetchCourse', () => {
  it('loads the annotated tree from the owner preview endpoint', async () => {
    fetchMock.mockResolvedValue(tree)
    const store = await loadStore()
    await store.fetchCourse('c1')
    expect(fetchMock).toHaveBeenCalledWith('/courses/c1/preview')
    expect(store.courseId).toBe('c1')
    expect(store.course?.modules).toHaveLength(2)
  })

  it('exposes effective visibility: published lesson in a draft module is hidden', async () => {
    fetchMock.mockResolvedValue(tree)
    const store = await loadStore()
    await store.fetchCourse('c1')
    expect(store.findLesson('l1')?.visible_to_student).toBe(true)
    expect(store.findLesson('l2')?.visible_to_student).toBe(false)
    // Its own flag is true, but the parent module is a draft → hidden.
    expect(store.findLesson('l3')?.is_published).toBe(true)
    expect(store.findLesson('l3')?.visible_to_student).toBe(false)
    expect(store.findModuleOfLesson('l3')?.id).toBe('m2')
  })
})

describe('dry-run completion', () => {
  it('markCompleted is local only — no API call', async () => {
    const store = await loadStore()
    store.markCompleted('l1')
    expect(store.isCompleted('l1')).toBe(true)
    expect(store.isCompleted('l2')).toBe(false)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('reset wipes progress, tree and entry point', async () => {
    fetchMock.mockResolvedValue(tree)
    const store = await loadStore()
    await store.fetchCourse('c1')
    store.markCompleted('l1')
    store.setEntryPoint('/courses/c1')
    store.reset()
    expect(store.course).toBeNull()
    expect(store.courseId).toBeNull()
    expect(store.isCompleted('l1')).toBe(false)
    expect(store.entryPoint).toBeNull()
  })
})
