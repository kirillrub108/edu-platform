/**
 * Assignments store: teacher list/create/publish/delete + student submit/grade
 * API wiring, optimistic update + rollback, and error-code mapping.
 *
 * Mirrors billing.test.ts: resetModules + dynamic import, Nuxt auto-imports
 * (ref, computed, useApi) stubbed as globals.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { computed, ref } from 'vue'

const fetchMock = vi.fn()

const loadStore = async () => {
  const { createPinia, setActivePinia } = await import('pinia')
  setActivePinia(createPinia())
  const mod = await import('../../src/stores/assignments')
  return { store: mod.useAssignmentsStore(), assignmentErrorMessage: mod.assignmentErrorMessage }
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

const teacherAssignment = (overrides = {}) => ({
  id: 'a1',
  lesson_id: 'L1',
  title: 'Essay',
  prompt: 'Write',
  max_points: 100,
  due_at: null,
  status: 'draft',
  attachments_enabled: true,
  max_files: 5,
  allowed_ext: ['pdf'],
  max_file_mb: 10,
  pass_threshold: null,
  created_at: '2026-06-12T00:00:00Z',
  updated_at: '2026-06-12T00:00:00Z',
  submission_count: 0,
  pending_count: 0,
  ...overrides,
})

describe('teacher actions', () => {
  it('fetchTeacher populates the per-lesson list', async () => {
    fetchMock.mockResolvedValue({ items: [teacherAssignment()], total: 1 })
    const { store } = await loadStore()
    await store.fetchTeacher('L1')
    expect(fetchMock).toHaveBeenCalledWith('/lessons/L1/assignments')
    expect(store.teacherState('L1').items).toHaveLength(1)
    expect(store.teacherState('L1').loading).toBe(false)
  })

  it('create appends the new assignment', async () => {
    const created = teacherAssignment({ id: 'a2', title: 'New' })
    fetchMock.mockResolvedValue(created)
    const { store } = await loadStore()
    const result = await store.create('L1', { title: 'New', prompt: 'p', max_points: 100 })
    expect(fetchMock).toHaveBeenCalledWith('/lessons/L1/assignments', {
      method: 'POST',
      body: { title: 'New', prompt: 'p', max_points: 100 },
    })
    expect(result.id).toBe('a2')
    expect(store.teacherState('L1').items.map((a) => a.id)).toContain('a2')
  })

  it('setStatus replaces the item with the published version', async () => {
    fetchMock.mockResolvedValueOnce({ items: [teacherAssignment()], total: 1 })
    const { store } = await loadStore()
    await store.fetchTeacher('L1')
    fetchMock.mockResolvedValueOnce(teacherAssignment({ status: 'published' }))
    await store.setStatus('L1', 'a1', 'publish')
    expect(fetchMock).toHaveBeenLastCalledWith('/assignments/a1/publish', { method: 'POST' })
    expect(store.teacherState('L1').items[0].status).toBe('published')
  })

  it('remove is optimistic and rolls back on failure', async () => {
    fetchMock.mockResolvedValueOnce({ items: [teacherAssignment()], total: 1 })
    const { store } = await loadStore()
    await store.fetchTeacher('L1')

    fetchMock.mockRejectedValueOnce({ response: { status: 500 } })
    await expect(store.remove('L1', 'a1')).rejects.toBeTruthy()
    // rolled back
    expect(store.teacherState('L1').items.map((a) => a.id)).toContain('a1')
  })
})

describe('student actions', () => {
  it('submitStudent posts text to the submit endpoint', async () => {
    fetchMock.mockResolvedValue({ id: 's1', status: 'submitted' })
    const { store } = await loadStore()
    await store.submitStudent('a1', 'my answer')
    expect(fetchMock).toHaveBeenCalledWith('/students/assignments/a1/submission/submit', {
      method: 'POST',
      body: { text_content: 'my answer' },
    })
  })

  it('grade posts points + feedback', async () => {
    fetchMock.mockResolvedValue({ id: 's1', status: 'returned' })
    const { store } = await loadStore()
    await store.grade('s1', { points_awarded: 80, feedback: 'good' })
    expect(fetchMock).toHaveBeenCalledWith('/submissions/s1/grade', {
      method: 'POST',
      body: { points_awarded: 80, feedback: 'good' },
    })
  })
})

describe('assignmentErrorMessage', () => {
  it('maps machine-readable codes to Russian', async () => {
    const { assignmentErrorMessage } = await loadStore()
    expect(assignmentErrorMessage({ data: { detail: { code: 'empty_submission' } } }, 'x')).toBe(
      'Добавьте текст ответа или прикрепите файл',
    )
    expect(assignmentErrorMessage({ response: { status: 429 } }, 'x')).toBe(
      'Слишком часто, подождите минуту',
    )
    expect(assignmentErrorMessage({ data: { detail: 'plain' } }, 'x')).toBe('plain')
    expect(assignmentErrorMessage({}, 'fallback')).toBe('fallback')
  })
})
