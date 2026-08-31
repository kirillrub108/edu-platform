/**
 * Lesson knowledge store: API wiring for materials/notes, optimistic delete +
 * rollback, reorder payload shape, and error-code mapping.
 *
 * Mirrors assignments.test.ts: resetModules + dynamic import, Nuxt auto-imports
 * (ref, computed, useApi) stubbed as globals.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { computed, ref } from 'vue'

const fetchMock = vi.fn()

const loadStore = async () => {
  const { createPinia, setActivePinia } = await import('pinia')
  setActivePinia(createPinia())
  const mod = await import('../../src/stores/lessonKnowledge')
  return { store: mod.useLessonKnowledgeStore(), knowledgeErrorMessage: mod.knowledgeErrorMessage }
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

const note = (overrides = {}) => ({
  id: 'n1',
  lesson_id: 'L1',
  title: 'Конспект',
  content: '# Заголовок',
  order: 0,
  created_by: 'u1',
  created_at: '2026-08-19T00:00:00Z',
  updated_at: '2026-08-19T00:00:00Z',
  ...overrides,
})

const material = (overrides = {}) => ({
  id: 'm1',
  lesson_id: 'L1',
  title: 'Методичка',
  description: null,
  original_filename: 'handout.pdf',
  content_type: 'application/pdf',
  size_bytes: 1024,
  uploaded_by: 'u1',
  created_at: '2026-08-19T00:00:00Z',
  updated_at: '2026-08-19T00:00:00Z',
  download_url: 'http://api.test/files/materials/L1/handout.pdf?sig=x',
  ...overrides,
})

const knowledge = (overrides = {}) => ({
  materials: [material()],
  notes: [note()],
  can_edit: true,
  limits: { max_files: 30, max_total_mb: 2048, allowed_ext: ['pdf'], note_max_chars: 50000 },
  ...overrides,
})

describe('fetch', () => {
  it('populates the per-lesson state from one knowledge call', async () => {
    fetchMock.mockResolvedValue(knowledge())
    const { store } = await loadStore()

    await store.fetch('L1')

    expect(fetchMock).toHaveBeenCalledWith('/lessons/L1/knowledge')
    const state = store.getState('L1')
    expect(state.materials).toHaveLength(1)
    expect(state.notes).toHaveLength(1)
    expect(state.canEdit).toBe(true)
    expect(state.limits?.max_files).toBe(30)
    expect(state.loaded).toBe(true)
    expect(state.loading).toBe(false)
  })

  it('records a readable error and stays unloaded on failure', async () => {
    fetchMock.mockRejectedValue({ response: { status: 500 } })
    const { store } = await loadStore()

    await store.fetch('L1')

    expect(store.getState('L1').error).toBeTruthy()
    expect(store.getState('L1').loaded).toBe(false)
  })

  it('keeps state separate per lesson', async () => {
    fetchMock.mockResolvedValue(knowledge({ notes: [] }))
    const { store } = await loadStore()
    await store.fetch('L1')

    expect(store.getState('L2').notes).toEqual([])
    expect(store.getState('L2').loaded).toBe(false)
  })
})

describe('materials', () => {
  it('uploads as multipart and appends the created material', async () => {
    fetchMock.mockResolvedValue(material({ id: 'm2' }))
    const { store } = await loadStore()

    await store.uploadMaterial('L1', new File(['x'], 'handout.pdf'), { title: 'Методичка' })

    const [path, options] = fetchMock.mock.calls[0]!
    expect(path).toBe('/lessons/L1/materials')
    expect(options.method).toBe('POST')
    expect(options.body).toBeInstanceOf(FormData)
    expect(store.getState('L1').materials.map((m) => m.id)).toEqual(['m2'])
  })

  it('rolls the list back when a delete fails', async () => {
    fetchMock.mockResolvedValueOnce(knowledge())
    const { store } = await loadStore()
    await store.fetch('L1')

    fetchMock.mockRejectedValueOnce({ data: { detail: { code: 'extension_not_allowed' } } })
    await expect(store.deleteMaterial('L1', 'm1')).rejects.toBeTruthy()

    expect(store.getState('L1').materials.map((m) => m.id)).toEqual(['m1'])
    expect(store.getState('L1').error).toBe('Недопустимый тип файла')
  })

  it('drops the material optimistically on success', async () => {
    fetchMock.mockResolvedValueOnce(knowledge())
    const { store } = await loadStore()
    await store.fetch('L1')

    fetchMock.mockResolvedValueOnce(undefined)
    await store.deleteMaterial('L1', 'm1')

    expect(store.getState('L1').materials).toEqual([])
  })
})

describe('notes', () => {
  it('sends the full ordering when moving a note down', async () => {
    fetchMock.mockResolvedValueOnce(
      knowledge({ notes: [note({ id: 'n1' }), note({ id: 'n2', order: 1 })] }),
    )
    const { store } = await loadStore()
    await store.fetch('L1')

    fetchMock.mockResolvedValueOnce([note({ id: 'n2' }), note({ id: 'n1', order: 1 })])
    await store.moveNote('L1', 'n1', 1)

    const [path, options] = fetchMock.mock.calls[1]!
    expect(path).toBe('/lessons/L1/notes/order')
    expect(options.method).toBe('PUT')
    expect(options.body).toEqual({ note_ids: ['n2', 'n1'] })
    expect(store.getState('L1').notes.map((n) => n.id)).toEqual(['n2', 'n1'])
  })

  it('does not call the API when the move would leave the list', async () => {
    fetchMock.mockResolvedValueOnce(knowledge())
    const { store } = await loadStore()
    await store.fetch('L1')
    fetchMock.mockClear()

    await store.moveNote('L1', 'n1', -1)

    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('restores the previous order when reorder fails', async () => {
    fetchMock.mockResolvedValueOnce(
      knowledge({ notes: [note({ id: 'n1' }), note({ id: 'n2', order: 1 })] }),
    )
    const { store } = await loadStore()
    await store.fetch('L1')

    fetchMock.mockRejectedValueOnce({ data: { detail: { code: 'invalid_note_order' } } })
    await expect(store.moveNote('L1', 'n1', 1)).rejects.toBeTruthy()

    expect(store.getState('L1').notes.map((n) => n.id)).toEqual(['n1', 'n2'])
  })

  it('appends a created note', async () => {
    fetchMock.mockResolvedValue(note({ id: 'n9' }))
    const { store } = await loadStore()

    await store.createNote('L1', { title: 'T', content: 'C' })

    expect(fetchMock).toHaveBeenCalledWith('/lessons/L1/notes', {
      method: 'POST',
      body: { title: 'T', content: 'C' },
    })
    expect(store.getState('L1').notes.map((n) => n.id)).toEqual(['n9'])
  })
})

describe('knowledgeErrorMessage', () => {
  it('prefers the backend human message over the code map', async () => {
    const { knowledgeErrorMessage } = await loadStore()
    const err = { data: { detail: { code: 'file_too_large', message: 'Файл 700 МБ, лимит 500' } } }
    expect(knowledgeErrorMessage(err, 'fallback')).toBe('Файл 700 МБ, лимит 500')
  })

  it('maps a bare code and falls back otherwise', async () => {
    const { knowledgeErrorMessage } = await loadStore()
    expect(knowledgeErrorMessage({ data: { detail: { code: 'too_many_notes' } } }, 'f')).toBe(
      'Превышено число конспектов',
    )
    expect(knowledgeErrorMessage({}, 'f')).toBe('f')
  })

  it('special-cases throttling', async () => {
    const { knowledgeErrorMessage } = await loadStore()
    expect(knowledgeErrorMessage({ response: { status: 429 } }, 'f')).toBe(
      'Слишком часто, подождите минуту',
    )
  })
})

// ── Signed-URL refresh: one request per lesson, not per broken image ──────────

describe('expired signed URLs', () => {
  const knowledgeResponse = (url: string) => ({
    materials: [
      { ...material(), id: 'm1', is_inline: true, download_url: `${url}#1` },
      { ...material(), id: 'm2', is_inline: true, download_url: `${url}#2` },
    ],
    notes: [],
    can_edit: true,
    limits: {
      max_files: 30,
      max_total_mb: 2048,
      allowed_ext: ['png'],
      note_max_chars: 50000,
      max_inline_files: 20,
      text_max_chars: 200000,
    },
  })

  it('collapses a burst of image errors into a single refetch', async () => {
    const { store } = await loadStore()
    let release: (v: unknown) => void = () => {}
    fetchMock.mockImplementation(
      () => new Promise((resolve) => { release = resolve }),
    )

    // 20 inline images signed together expire together and all fire @error.
    const bursts = Array.from({ length: 20 }, (_, i) =>
      store.refreshExpiredUrls('L1', `http://files/img.png?sig=old${i}`),
    )
    expect(fetchMock).toHaveBeenCalledTimes(1)

    release(knowledgeResponse('http://files/img.png?sig=new'))
    await Promise.all(bursts)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(store.getState('L1').materials[0].download_url).toContain('sig=new')
  })

  it('does not retry the same URL twice — a broken object cannot loop', async () => {
    const { store } = await loadStore()
    fetchMock.mockResolvedValue(knowledgeResponse('http://files/img.png?sig=new'))

    await store.refreshExpiredUrls('L1', 'http://files/broken.png?sig=x')
    await store.refreshExpiredUrls('L1', 'http://files/broken.png?sig=x')

    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('ensureLoaded fetches once and is a no-op afterwards', async () => {
    const { store } = await loadStore()
    fetchMock.mockResolvedValue(knowledgeResponse('http://files/img.png?sig=a'))

    // Two consumers (page material map + KnowledgePanel) race on mount.
    await Promise.all([store.ensureLoaded('L1'), store.ensureLoaded('L1')])
    expect(fetchMock).toHaveBeenCalledTimes(1)

    await store.ensureLoaded('L1')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
