import { defineStore } from 'pinia'

export interface CommentAuthor {
  id: string
  full_name: string | null
  role: 'teacher' | 'student'
}

export interface Comment {
  id: string
  lesson_id: string
  content: string
  author: CommentAuthor
  created_at: string
  updated_at: string
  is_edited: boolean
}

interface CommentListResponse {
  items: Comment[]
  total: number
}

interface LessonComments {
  items: Comment[]
  total: number
  loading: boolean
  error: string | null
}

const POLL_INTERVAL_MS = 15_000

function emptyState(): LessonComments {
  return { items: [], total: 0, loading: false, error: null }
}

export const useCommentsStore = defineStore('comments', () => {
  const { apiFetch } = useApi()

  const byLesson = ref<Record<string, LessonComments>>({})

  let pollTimer: ReturnType<typeof setInterval> | null = null
  let pollingLessonId: string | null = null

  const getState = (lessonId: string): LessonComments => {
    if (!byLesson.value[lessonId]) {
      byLesson.value[lessonId] = emptyState()
    }
    return byLesson.value[lessonId]!
  }

  const fetch = async (lessonId: string): Promise<void> => {
    const state = getState(lessonId)
    state.loading = true
    state.error = null
    try {
      const res = await apiFetch<CommentListResponse>(
        `/lessons/${lessonId}/comments?limit=100&offset=0`,
      )
      state.items = res.items
      state.total = res.total
    } catch (err: any) {
      state.error = err?.data?.detail ?? 'Не удалось загрузить комментарии'
    } finally {
      state.loading = false
    }
  }

  const create = async (lessonId: string, content: string): Promise<void> => {
    const state = getState(lessonId)
    state.error = null
    try {
      const created = await apiFetch<Comment>(`/lessons/${lessonId}/comments`, {
        method: 'POST',
        body: { content },
      })
      state.items = [created, ...state.items]
      state.total += 1
    } catch (err: any) {
      const status = err?.response?.status
      state.error =
        status === 429
          ? 'Слишком часто, подождите минуту'
          : (err?.data?.detail ?? 'Не удалось отправить комментарий')
      throw err
    }
  }

  const update = async (
    lessonId: string,
    commentId: string,
    content: string,
  ): Promise<void> => {
    const state = getState(lessonId)
    const idx = state.items.findIndex((c) => c.id === commentId)
    const prev = idx >= 0 ? { ...state.items[idx]! } : null

    if (idx >= 0) {
      state.items[idx] = {
        ...state.items[idx]!,
        content,
        updated_at: new Date().toISOString(),
        is_edited: true,
      }
    }
    try {
      const updated = await apiFetch<Comment>(`/comments/${commentId}`, {
        method: 'PATCH',
        body: { content },
      })
      if (idx >= 0) state.items[idx] = updated
    } catch (err: any) {
      if (prev && idx >= 0) state.items[idx] = prev
      const status = err?.response?.status
      state.error =
        status === 429
          ? 'Слишком часто, подождите минуту'
          : (err?.data?.detail ?? 'Не удалось сохранить изменения')
      throw err
    }
  }

  const remove = async (lessonId: string, commentId: string): Promise<void> => {
    const state = getState(lessonId)
    const idx = state.items.findIndex((c) => c.id === commentId)
    const prev = idx >= 0 ? state.items[idx]! : null
    if (idx >= 0) {
      state.items = state.items.filter((c) => c.id !== commentId)
      state.total = Math.max(0, state.total - 1)
    }
    try {
      await apiFetch(`/comments/${commentId}`, { method: 'DELETE' })
    } catch (err: any) {
      if (prev) {
        state.items = [prev, ...state.items]
        state.total += 1
      }
      state.error = err?.data?.detail ?? 'Не удалось удалить комментарий'
      throw err
    }
  }

  const stopPolling = (): void => {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
    pollingLessonId = null
  }

  const startPolling = (lessonId: string): void => {
    if (pollingLessonId === lessonId && pollTimer) return
    stopPolling()
    pollingLessonId = lessonId
    pollTimer = setInterval(() => {
      if (pollingLessonId) void fetch(pollingLessonId)
    }, POLL_INTERVAL_MS)
  }

  return {
    byLesson,
    getState,
    fetch,
    create,
    update,
    remove,
    startPolling,
    stopPolling,
  }
})
