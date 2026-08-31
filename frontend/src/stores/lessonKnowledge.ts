import { defineStore } from 'pinia'

export interface KnowledgeMaterial {
  id: string
  lesson_id: string
  title: string
  description: string | null
  original_filename: string
  content_type: string | null
  size_bytes: number
  /** Referenced from the lesson's markdown body; hidden from the «Файлы» list. */
  is_inline: boolean
  uploaded_by: string | null
  created_at: string
  updated_at: string
  download_url: string
}

export interface KnowledgeNote {
  id: string
  lesson_id: string
  title: string
  content: string
  order: number
  created_by: string | null
  created_at: string
  updated_at: string
}

export interface KnowledgeLimits {
  max_files: number
  max_total_mb: number
  allowed_ext: string[]
  note_max_chars: number
  max_inline_files: number
  text_max_chars: number
}

export interface KnowledgeState {
  materials: KnowledgeMaterial[]
  notes: KnowledgeNote[]
  /** Server-decided: true only for the owning teacher. */
  canEdit: boolean
  limits: KnowledgeLimits | null
  loaded: boolean
  loading: boolean
  error: string | null
}

interface KnowledgeResponse {
  materials: KnowledgeMaterial[]
  notes: KnowledgeNote[]
  can_edit: boolean
  limits: KnowledgeLimits
}

function emptyState(): KnowledgeState {
  return {
    materials: [],
    notes: [],
    canEdit: false,
    limits: null,
    loaded: false,
    loading: false,
    error: null,
  }
}

// Machine-readable backend `detail.code` → human Russian message.
export const KNOWLEDGE_ERROR_CODES: Record<string, string> = {
  too_many_files: 'Превышено число материалов',
  file_too_large: 'Файл слишком большой',
  materials_too_large: 'Суммарный объём материалов слишком большой',
  extension_not_allowed: 'Недопустимый тип файла',
  too_many_inline_files: 'Превышено число вложений в тексте урока',
  too_many_notes: 'Превышено число конспектов',
  invalid_note_order: 'Не удалось изменить порядок конспектов',
}

export function knowledgeErrorMessage(err: any, fallback: string): string {
  const status = err?.response?.status
  if (status === 429) return 'Слишком часто, подождите минуту'
  if (status === 413) return 'Файл слишком большой'
  const detail = err?.data?.detail
  if (typeof detail === 'string') return detail
  // The backend sends a specific human-readable `message` for limit errors
  // (which file, its size, the limit) — prefer it over the generic map.
  if (typeof detail?.message === 'string') return detail.message
  if (detail?.code) return KNOWLEDGE_ERROR_CODES[detail.code] ?? detail.code
  return fallback
}

export const useLessonKnowledgeStore = defineStore('lessonKnowledge', () => {
  const { apiFetch } = useApi()

  const byLesson = ref<Record<string, KnowledgeState>>({})

  const getState = (lessonId: string): KnowledgeState => {
    if (!byLesson.value[lessonId]) byLesson.value[lessonId] = emptyState()
    return byLesson.value[lessonId]!
  }

  const apply = (lessonId: string, res: KnowledgeResponse): void => {
    const state = getState(lessonId)
    state.materials = res.materials
    state.notes = res.notes
    state.canEdit = res.can_edit
    state.limits = res.limits
  }

  const fetch = async (lessonId: string): Promise<void> => {
    const state = getState(lessonId)
    state.loading = true
    state.error = null
    try {
      apply(lessonId, await apiFetch<KnowledgeResponse>(`/lessons/${lessonId}/knowledge`))
      state.loaded = true
    } catch (err: any) {
      state.error = knowledgeErrorMessage(err, 'Не удалось загрузить базу знаний')
    } finally {
      state.loading = false
    }
  }

  // ── Signed-URL refresh (singleflight) ──────────────────────────────────────
  // Material download URLs expire after SIGNED_URL_TTL_MATERIAL. A text lesson
  // can hold ~20 inline images signed within the same second, so they all expire
  // together and every <img> fires @error at once. Without this, that is 20
  // identical GETs; with it, the first one starts the request and the rest await
  // it. Mirrors the singleflight `refreshPromise` in composables/useApi.ts.
  const inFlight: Record<string, Promise<void> | undefined> = {}
  // Per-URL guard: a genuinely broken object must not spin refetch forever.
  const retriedUrls = new Set<string>()

  const refresh = (lessonId: string): Promise<void> => {
    const pending = inFlight[lessonId]
    if (pending) return pending
    const run = fetch(lessonId).finally(() => {
      delete inFlight[lessonId]
    })
    inFlight[lessonId] = run
    return run
  }

  /** Load once per lesson; concurrent callers share the same request. */
  const ensureLoaded = (lessonId: string): Promise<void> => {
    const state = getState(lessonId)
    if (state.loaded) return Promise.resolve()
    return refresh(lessonId)
  }

  /**
   * Called from an inline <img> @error. Re-signs the lesson's material URLs once,
   * no matter how many images failed; a URL that fails again after a refresh is
   * genuinely broken and is not retried.
   */
  const refreshExpiredUrls = async (lessonId: string, failedUrl: string): Promise<void> => {
    if (retriedUrls.has(failedUrl)) return
    retriedUrls.add(failedUrl)
    await refresh(lessonId)
  }

  // ── Materials ──────────────────────────────────────────────────────────────

  const uploadMaterial = async (
    lessonId: string,
    file: File,
    meta: { title?: string; description?: string; isInline?: boolean } = {},
  ): Promise<KnowledgeMaterial> => {
    const state = getState(lessonId)
    const form = new FormData()
    form.append('file', file)
    if (meta.title) form.append('title', meta.title)
    if (meta.description) form.append('description', meta.description)
    if (meta.isInline) form.append('is_inline', 'true')
    try {
      const created = await apiFetch<KnowledgeMaterial>(`/lessons/${lessonId}/materials`, {
        method: 'POST',
        body: form,
      })
      state.materials = [...state.materials, created]
      return created
    } catch (err: any) {
      state.error = knowledgeErrorMessage(err, 'Не удалось загрузить файл')
      throw err
    }
  }

  const updateMaterial = async (
    lessonId: string,
    materialId: string,
    payload: { title?: string; description?: string | null },
  ): Promise<KnowledgeMaterial> => {
    const state = getState(lessonId)
    try {
      const updated = await apiFetch<KnowledgeMaterial>(
        `/lessons/${lessonId}/materials/${materialId}`,
        { method: 'PATCH', body: payload },
      )
      const idx = state.materials.findIndex((m) => m.id === materialId)
      if (idx >= 0) state.materials[idx] = updated
      return updated
    } catch (err: any) {
      state.error = knowledgeErrorMessage(err, 'Не удалось сохранить материал')
      throw err
    }
  }

  const deleteMaterial = async (lessonId: string, materialId: string): Promise<void> => {
    const state = getState(lessonId)
    const prev = state.materials
    state.materials = state.materials.filter((m) => m.id !== materialId)
    try {
      await apiFetch(`/lessons/${lessonId}/materials/${materialId}`, { method: 'DELETE' })
    } catch (err: any) {
      state.materials = prev
      state.error = knowledgeErrorMessage(err, 'Не удалось удалить материал')
      throw err
    }
  }

  // ── Notes ──────────────────────────────────────────────────────────────────

  const createNote = async (
    lessonId: string,
    payload: { title: string; content: string },
  ): Promise<KnowledgeNote> => {
    const state = getState(lessonId)
    try {
      const created = await apiFetch<KnowledgeNote>(`/lessons/${lessonId}/notes`, {
        method: 'POST',
        body: payload,
      })
      state.notes = [...state.notes, created]
      return created
    } catch (err: any) {
      state.error = knowledgeErrorMessage(err, 'Не удалось создать конспект')
      throw err
    }
  }

  const updateNote = async (
    lessonId: string,
    noteId: string,
    payload: { title?: string; content?: string },
  ): Promise<KnowledgeNote> => {
    const state = getState(lessonId)
    try {
      const updated = await apiFetch<KnowledgeNote>(`/lessons/${lessonId}/notes/${noteId}`, {
        method: 'PATCH',
        body: payload,
      })
      const idx = state.notes.findIndex((n) => n.id === noteId)
      if (idx >= 0) state.notes[idx] = updated
      return updated
    } catch (err: any) {
      state.error = knowledgeErrorMessage(err, 'Не удалось сохранить конспект')
      throw err
    }
  }

  const deleteNote = async (lessonId: string, noteId: string): Promise<void> => {
    const state = getState(lessonId)
    const prev = state.notes
    state.notes = state.notes.filter((n) => n.id !== noteId)
    try {
      await apiFetch(`/lessons/${lessonId}/notes/${noteId}`, { method: 'DELETE' })
    } catch (err: any) {
      state.notes = prev
      state.error = knowledgeErrorMessage(err, 'Не удалось удалить конспект')
      throw err
    }
  }

  /** Move one note up/down; the server takes the full ordering and returns it back. */
  const moveNote = async (lessonId: string, noteId: string, delta: number): Promise<void> => {
    const state = getState(lessonId)
    const prev = state.notes
    const ids = prev.map((n) => n.id)
    const from = ids.indexOf(noteId)
    const to = from + delta
    if (from < 0 || to < 0 || to >= ids.length) return

    ids.splice(to, 0, ids.splice(from, 1)[0]!)
    // Optimistic: reorder locally so the list doesn't jump on a slow network.
    state.notes = ids.map((id) => prev.find((n) => n.id === id)!)
    try {
      state.notes = await apiFetch<KnowledgeNote[]>(`/lessons/${lessonId}/notes/order`, {
        method: 'PUT',
        body: { note_ids: ids },
      })
    } catch (err: any) {
      state.notes = prev
      state.error = knowledgeErrorMessage(err, 'Не удалось изменить порядок')
      throw err
    }
  }

  return {
    byLesson,
    getState,
    fetch,
    ensureLoaded,
    refreshExpiredUrls,
    uploadMaterial,
    updateMaterial,
    deleteMaterial,
    createNote,
    updateNote,
    deleteNote,
    moveNote,
  }
})
