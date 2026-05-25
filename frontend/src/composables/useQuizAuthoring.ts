export interface TeacherQuizQuestion {
  id: string
  lesson_id: string
  question: string
  options: string[]
  correct_index: number
  order: number
  created_at: string
  updated_at: string
}

export interface QuestionFlag {
  question_id: string
  kind: 'ok' | 'wrong_answer' | 'ambiguous' | 'duplicate'
  note: string
}

export type RegenerateMode = 'rephrase' | 'harder' | 'easier' | 'improve_distractors'

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

  const questions = ref<TeacherQuizQuestion[]>([])
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

  const stopPolling = () => {
    if (poller) { clearInterval(poller); poller = null }
  }

  const load = async () => {
    loading.value = true
    loadError.value = ''
    try {
      questions.value = await apiFetch<TeacherQuizQuestion[]>(
        `/lessons/${lessonId.value}/quiz`,
      )
    } catch (e: any) {
      loadError.value = e?.data?.detail ?? 'Не удалось загрузить вопросы'
    } finally {
      loading.value = false
    }
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
        await load()
      } else if (res.status === 'FAILURE' || res.error) {
        stopPolling()
        generating.value = false
        taskId.value = null
        generationError.value = res.error ?? 'Ошибка генерации'
      }
    } catch { /* network glitch — keep polling */ }
  }

  const generate = async (numQuestions?: number, numOptions?: number) => {
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
            num_questions: numQuestions ?? null,
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

  const patchQuestion = async (
    q: TeacherQuizQuestion,
    patch: Partial<Pick<TeacherQuizQuestion, 'question' | 'options' | 'correct_index' | 'order'>>,
  ): Promise<TeacherQuizQuestion | null> => {
    savingIds.value.add(q.id)
    try {
      const updated = await apiFetch<TeacherQuizQuestion>(
        `/lessons/${lessonId.value}/quiz/${q.id}`,
        { method: 'PATCH', body: patch },
      )
      const idx = questions.value.findIndex(x => x.id === q.id)
      if (idx >= 0) questions.value[idx] = updated
      return updated
    } catch (e: any) {
      // Surface validation errors to caller.
      throw e
    } finally {
      savingIds.value.delete(q.id)
    }
  }

  const regenerate = async (q: TeacherQuizQuestion, mode: RegenerateMode) => {
    regenIds.value.add(q.id)
    try {
      const updated = await apiFetch<TeacherQuizQuestion>(
        `/lessons/${lessonId.value}/quiz/${q.id}/regenerate`,
        { method: 'POST', body: { mode } },
      )
      const idx = questions.value.findIndex(x => x.id === q.id)
      if (idx >= 0) questions.value[idx] = updated
    } finally {
      regenIds.value.delete(q.id)
    }
  }

  const deleteQuestion = async (q: TeacherQuizQuestion) => {
    await apiFetch(`/lessons/${lessonId.value}/quiz/${q.id}`, { method: 'DELETE' })
    questions.value = questions.value.filter(x => x.id !== q.id)
    flags.value = flags.value.filter(f => f.question_id !== q.id)
  }

  const runQaReview = async () => {
    qaRunning.value = true
    qaError.value = ''
    try {
      flags.value = await apiFetch<QuestionFlag[]>(
        `/lessons/${lessonId.value}/quiz/qa-review`,
        { method: 'POST' },
      )
    } catch (e: any) {
      qaError.value = e?.data?.detail ?? 'Не удалось выполнить проверку'
    } finally {
      qaRunning.value = false
    }
  }

  const flagFor = (questionId: string): QuestionFlag | undefined =>
    flags.value.find(f => f.question_id === questionId)

  // Resume polling if the lesson page reloads mid-generation.
  const resumeIfRunning = (existingTaskId: string | null) => {
    if (!existingTaskId || taskId.value) return
    taskId.value = existingTaskId
    generating.value = true
    stopPolling()
    poller = setInterval(pollStatus, 2000)
  }

  onUnmounted(stopPolling)

  return {
    questions, loading, loadError,
    generating, generationStep, generationDone, generationTotal, generationError,
    regenIds, savingIds,
    flags, qaRunning, qaError, flagFor,
    load, generate, patchQuestion, regenerate, deleteQuestion, runQaReview,
    resumeIfRunning,
  }
}
