/**
 * Teacher-side quiz authoring: settings, publish, polymorphic question CRUD,
 * generation polling, per-question AI ops, AI review, manual override.
 *
 * The API exposes JSONB `payload` per question; this composable doesn't try
 * to be type-clever about it — components render the right form by `type`
 * and assemble the payload back into a plain object on save.
 */

export type QuestionType =
  | 'single_choice'
  | 'multiple_choice'
  | 'true_false'
  | 'short_answer'
  | 'essay'
  | 'matching'
  | 'ordering'
  | 'fill_blank'

export interface TeacherQuestion {
  id: string
  quiz_id: string
  type: QuestionType
  payload: Record<string, any>
  weight: string
  order: number
}

export interface QuizSettings {
  id: string
  lesson_id: string
  status: 'draft' | 'published'
  attempts_allowed: number | null
  pass_threshold: string
  show_answers: boolean
  shuffle: boolean
  generation_task_id: string | null
}

export interface QuestionFlag {
  question_id: string
  kind: 'ok' | 'wrong_answer' | 'ambiguous' | 'duplicate'
  note: string
}

export type RegenerateMode = 'rephrase' | 'harder' | 'easier' | 'improve_distractors'

/** Subset of QuestionType the LLM generator supports. */
export type GeneratableQuestionType = Extract<
  QuestionType,
  'single_choice' | 'multiple_choice' | 'true_false' | 'short_answer'
>

/** How many questions of one type to generate. 0 = exclude the type. */
export interface QuizTypeCount {
  type: GeneratableQuestionType
  count: number
}

export interface QuizGenerationTypeOption {
  type: GeneratableQuestionType
  default_count: number
}

/** Bounds + defaults served from backend constants.py — never restated in the UI. */
export interface QuizGenerationOptions {
  types: QuizGenerationTypeOption[]
  min_per_type: number
  max_per_type: number
  min_total: number
  max_total: number
  num_options: number
}

export function totalRequestedQuestions(counts: QuizTypeCount[]): number {
  return counts.reduce((sum, c) => sum + (Number.isFinite(c.count) ? c.count : 0), 0)
}

/** Clamp a raw input value to an integer inside the per-type bounds. */
export function clampTypeCount(value: number, limits: QuizGenerationOptions): number {
  if (!Number.isFinite(value)) return limits.min_per_type
  return Math.min(limits.max_per_type, Math.max(limits.min_per_type, Math.round(value)))
}

/**
 * Validate the requested per-type counts against the server-served limits.
 * Returns a user-facing message, or null when the request may be sent.
 */
export function generationCountsError(
  counts: QuizTypeCount[],
  limits: QuizGenerationOptions | null,
): string | null {
  if (!limits) return 'Лимиты генерации не загружены'
  const outOfRange = counts.some(
    c => !Number.isInteger(c.count) || c.count < limits.min_per_type || c.count > limits.max_per_type,
  )
  if (outOfRange) {
    return `Количество на тип — целое от ${limits.min_per_type} до ${limits.max_per_type}`
  }
  const total = totalRequestedQuestions(counts)
  if (total < limits.min_total) return 'Укажите хотя бы один вопрос'
  if (total > limits.max_total) return `Всего не больше ${limits.max_total} вопросов`
  return null
}

interface GenerationStatus {
  task_id: string
  status: string
  step?: string | null
  done?: number | null
  total?: number | null
  error?: string | null
}

export function useQuizAuthoring(lessonId: Readonly<Ref<string>>) {
  const { apiFetch } = useApi()

  const settings = ref<QuizSettings | null>(null)
  const questions = ref<TeacherQuestion[]>([])
  const generationOptions = ref<QuizGenerationOptions | null>(null)
  const loading = ref(false)
  const loadError = ref('')

  const generating = ref(false)
  const generationStep = ref('')
  const generationDone = ref(0)
  const generationTotal = ref(0)
  const generationError = ref('')
  const taskId = ref<string | null>(null)
  let poller: ReturnType<typeof setInterval> | null = null

  const regenIds = ref<Set<string>>(new Set())
  const savingIds = ref<Set<string>>(new Set())

  const flags = ref<QuestionFlag[]>([])
  const qaRunning = ref(false)
  const qaError = ref('')

  const isPublished = computed(() => settings.value?.status === 'published')

  const stopPolling = () => {
    if (poller) { clearInterval(poller); poller = null }
  }

  const load = async () => {
    loading.value = true
    loadError.value = ''
    try {
      const [s, qs, opts] = await Promise.all([
        apiFetch<QuizSettings>(`/lessons/${lessonId.value}/quiz`),
        apiFetch<TeacherQuestion[]>(`/lessons/${lessonId.value}/quiz/questions`),
        apiFetch<QuizGenerationOptions>(`/lessons/${lessonId.value}/quiz/generation-options`),
      ])
      settings.value = s
      questions.value = qs
      generationOptions.value = opts
      if (s.generation_task_id && !taskId.value) {
        taskId.value = s.generation_task_id
        generating.value = true
        stopPolling()
        poller = setInterval(pollStatus, 2000)
      }
    } catch (e: any) {
      loadError.value = e?.data?.detail ?? 'Не удалось загрузить тест'
    } finally {
      loading.value = false
    }
  }

  const updateSettings = async (patch: Partial<{
    attempts_allowed: number | null
    pass_threshold: string
    show_answers: boolean
    shuffle: boolean
  }>) => {
    settings.value = await apiFetch<QuizSettings>(
      `/lessons/${lessonId.value}/quiz`,
      { method: 'PUT', body: patch },
    )
  }

  const publish = async () => {
    settings.value = await apiFetch<QuizSettings>(
      `/lessons/${lessonId.value}/quiz/publish`, { method: 'POST' },
    )
  }
  const unpublish = async () => {
    settings.value = await apiFetch<QuizSettings>(
      `/lessons/${lessonId.value}/quiz/unpublish`, { method: 'POST' },
    )
  }

  const pollStatus = async () => {
    if (!taskId.value) return
    try {
      const res = await apiFetch<GenerationStatus>(
        `/lessons/${lessonId.value}/quiz/generation-status/${taskId.value}`,
      )
      generationStep.value = res.step ?? ''
      generationDone.value = res.done ?? 0
      generationTotal.value = res.total ?? 0
      if (res.status === 'SUCCESS') {
        stopPolling()
        generating.value = false
        taskId.value = null
        if (res.error) {
          generationError.value = res.error
        } else {
          await load()
        }
      } else if (res.status === 'FAILURE' || res.error) {
        stopPolling()
        generating.value = false
        taskId.value = null
        generationError.value = res.error ?? 'Ошибка генерации'
      }
    } catch { /* network glitch — keep polling */ }
  }

  const generate = async (typeCounts: QuizTypeCount[], numOptions?: number) => {
    const invalid = generationCountsError(typeCounts, generationOptions.value)
    if (invalid) {
      generationError.value = invalid
      return
    }
    generationError.value = ''
    flags.value = []
    generating.value = true
    stopPolling()
    try {
      const res = await apiFetch<{ task_id: string }>(
        `/lessons/${lessonId.value}/quiz/generate`,
        {
          method: 'POST',
          body: {
            type_counts: typeCounts.filter(c => c.count > 0),
            num_options: numOptions ?? null,
          },
        },
      )
      taskId.value = res.task_id
      poller = setInterval(pollStatus, 2000)
    } catch (e: any) {
      generating.value = false
      generationError.value = e?.data?.detail ?? 'Не удалось запустить генерацию'
    }
  }

  const createQuestion = async (
    type: QuestionType,
    payload: Record<string, any>,
    weight = 1.0,
  ): Promise<TeacherQuestion> => {
    const created = await apiFetch<TeacherQuestion>(
      `/lessons/${lessonId.value}/quiz/questions`,
      { method: 'POST', body: { type, payload, weight: weight.toString(), order: 0 } },
    )
    questions.value = [...questions.value, created]
    return created
  }

  const patchQuestion = async (
    q: TeacherQuestion,
    patch: Partial<{ payload: Record<string, any>; weight: string; order: number }>,
  ): Promise<TeacherQuestion> => {
    savingIds.value.add(q.id)
    try {
      const updated = await apiFetch<TeacherQuestion>(
        `/lessons/${lessonId.value}/quiz/questions/${q.id}`,
        { method: 'PATCH', body: patch },
      )
      const idx = questions.value.findIndex(x => x.id === q.id)
      if (idx >= 0) questions.value[idx] = updated
      return updated
    } finally {
      savingIds.value.delete(q.id)
    }
  }

  const deleteQuestion = async (q: TeacherQuestion) => {
    await apiFetch(`/lessons/${lessonId.value}/quiz/questions/${q.id}`, { method: 'DELETE' })
    questions.value = questions.value.filter(x => x.id !== q.id)
    flags.value = flags.value.filter(f => f.question_id !== q.id)
  }

  const reorderQuestions = async (orderedIds: string[]) => {
    questions.value = await apiFetch<TeacherQuestion[]>(
      `/lessons/${lessonId.value}/quiz/questions/reorder`,
      { method: 'POST', body: { order: orderedIds } },
    )
  }

  const regenerate = async (q: TeacherQuestion, mode: RegenerateMode) => {
    regenIds.value.add(q.id)
    try {
      const updated = await apiFetch<TeacherQuestion>(
        `/lessons/${lessonId.value}/quiz/questions/${q.id}/regenerate`,
        { method: 'POST', body: { mode } },
      )
      const idx = questions.value.findIndex(x => x.id === q.id)
      if (idx >= 0) questions.value[idx] = updated
    } finally {
      regenIds.value.delete(q.id)
    }
  }

  const runAiReview = async () => {
    qaRunning.value = true
    qaError.value = ''
    try {
      flags.value = await apiFetch<QuestionFlag[]>(
        `/lessons/${lessonId.value}/quiz/ai-review`,
        { method: 'POST' },
      )
    } catch (e: any) {
      qaError.value = e?.data?.detail ?? 'Не удалось выполнить проверку'
    } finally {
      qaRunning.value = false
    }
  }

  const flagFor = (qid: string): QuestionFlag | undefined =>
    flags.value.find(f => f.question_id === qid)

  onUnmounted(stopPolling)

  return {
    settings, questions, generationOptions, loading, loadError,
    isPublished,
    generating, generationStep, generationDone, generationTotal, generationError,
    regenIds, savingIds,
    flags, qaRunning, qaError, flagFor,
    load, updateSettings, publish, unpublish,
    generate, createQuestion, patchQuestion, deleteQuestion, reorderQuestions,
    regenerate, runAiReview,
  }
}
