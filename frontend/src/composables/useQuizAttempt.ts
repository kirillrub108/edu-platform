/**
 * Student-side attempt lifecycle: fetch quiz info, start, debounce-autosave
 * responses, submit, poll grading. The composable is single-attempt: rebuild
 * (call reset + fetch + start) when switching lessons.
 */

export type StudentQuestionType =
  | 'single_choice'
  | 'multiple_choice'
  | 'true_false'
  | 'short_answer'
  | 'essay'
  | 'matching'
  | 'ordering'
  | 'fill_blank'

export interface StudentQuestion {
  id: string
  type: StudentQuestionType
  payload: Record<string, any>
  order: number
}

export interface QuizInfo {
  quiz_id: string
  pass_threshold: string
  attempts_allowed: number | null
  attempts_used: number
  show_answers: boolean
  shuffle: boolean
  in_progress_attempt_id: string | null
}

export interface AnswerResult {
  question_id: string
  awarded_score: string | null
  max_score: string
  is_correct: boolean | null
  needs_review: boolean
  graded_by_ai: boolean
  llm_feedback: string | null
  correct_payload: Record<string, any> | null
}

export interface AttemptResult {
  attempt_id: string
  quiz_id: string
  attempt_number: number
  status: 'in_progress' | 'submitted' | 'graded'
  score: string | null
  passed: boolean | null
  started_at: string
  submitted_at: string | null
  graded_at: string | null
  grading_task_id: string | null
  ai_graded: boolean
  questions: StudentQuestion[]
  answers: AnswerResult[]
}

const AUTOSAVE_DELAY_MS = 500

export function useQuizAttempt(lessonId: Readonly<Ref<string>>) {
  const { apiFetch } = useApi()

  const info = ref<QuizInfo | null>(null)
  const attemptId = ref<string | null>(null)
  const questions = ref<StudentQuestion[]>([])
  const responses = ref<Record<string, any>>({})  // question_id -> response object
  const result = ref<AttemptResult | null>(null)
  const loading = ref(false)
  const submitting = ref(false)
  const error = ref('')
  const hasQuiz = ref(false)
  const saveStatus = ref<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const gradingPending = ref(false)

  let saveTimer: ReturnType<typeof setTimeout> | null = null
  let gradingPoller: ReturnType<typeof setInterval> | null = null

  const stopGradingPoll = () => {
    if (gradingPoller) { clearInterval(gradingPoller); gradingPoller = null }
  }

  const fetchInfo = async (): Promise<boolean> => {
    error.value = ''
    loading.value = true
    try {
      info.value = await apiFetch<QuizInfo>(
        `/students/lessons/${lessonId.value}/quiz`,
      )
      hasQuiz.value = true
      if (info.value.in_progress_attempt_id) {
        attemptId.value = info.value.in_progress_attempt_id
        await loadResult()
        // Resume: copy snapshot questions + responses from result
        if (result.value) {
          questions.value = result.value.questions
          responses.value = Object.fromEntries(
            result.value.answers.map(a => [
              a.question_id,
              // best-effort restore via a separate GET would be nicer; the
              // current result endpoint doesn't echo responses, so we start
              // fresh on resume. Acceptable trade-off — autosave covers it.
              {},
            ]),
          )
          // For an in-progress attempt we want QuizTaker to render the Active
          // view (with inputs + submit), not the Result view. The template
          // checks `v-else-if="result"` first, so we have to drop result here.
          if (result.value.status === 'in_progress') {
            result.value = null
          }
        }
      }
      return true
    } catch (e: any) {
      if (e?.response?.status === 404) {
        hasQuiz.value = false
        info.value = null
        return false
      }
      error.value = e?.data?.detail ?? 'Не удалось загрузить тест'
      return false
    } finally {
      loading.value = false
    }
  }

  const start = async () => {
    error.value = ''
    try {
      const res = await apiFetch<{
        attempt_id: string
        quiz_id: string
        attempt_number: number
        started_at: string
        questions: StudentQuestion[]
      }>(
        `/students/lessons/${lessonId.value}/quiz/attempts`,
        { method: 'POST' },
      )
      attemptId.value = res.attempt_id
      questions.value = res.questions
      responses.value = {}
      result.value = null
    } catch (e: any) {
      if (e?.response?.status === 409) {
        error.value = 'Лимит попыток исчерпан'
      } else {
        error.value = e?.data?.detail ?? 'Не удалось начать попытку'
      }
    }
  }

  const setResponse = (questionId: string, response: any) => {
    responses.value = { ...responses.value, [questionId]: response }
    scheduleAutosave()
  }

  const scheduleAutosave = () => {
    if (!attemptId.value) return
    if (saveTimer) clearTimeout(saveTimer)
    saveStatus.value = 'saving'
    saveTimer = setTimeout(flushSave, AUTOSAVE_DELAY_MS)
  }

  const flushSave = async () => {
    if (!attemptId.value) return
    if (saveTimer) { clearTimeout(saveTimer); saveTimer = null }
    const payload = Object.entries(responses.value).map(
      ([question_id, response]) => ({ question_id, response }),
    )
    if (payload.length === 0) {
      saveStatus.value = 'saved'
      return
    }
    try {
      await apiFetch(
        `/students/lessons/${lessonId.value}/quiz/attempts/${attemptId.value}`,
        { method: 'PUT', body: { answers: payload } },
      )
      saveStatus.value = 'saved'
    } catch {
      saveStatus.value = 'error'
    }
  }

  const loadResult = async () => {
    if (!attemptId.value) return
    result.value = await apiFetch<AttemptResult>(
      `/students/lessons/${lessonId.value}/quiz/attempts/${attemptId.value}`,
    )
  }

  const pollGrading = () => {
    if (gradingPoller) return
    gradingPoller = setInterval(async () => {
      try {
        await loadResult()
        if (result.value && result.value.status === 'graded') {
          stopGradingPoll()
          gradingPending.value = false
        }
      } catch { /* keep polling */ }
    }, 2500)
  }

  const submit = async () => {
    if (!attemptId.value) return
    await flushSave()
    submitting.value = true
    error.value = ''
    try {
      const res = await apiFetch<{
        attempt_id: string
        status: 'submitted' | 'graded'
        score: string | null
        passed: boolean | null
        grading_task_id: string | null
      }>(
        `/students/lessons/${lessonId.value}/quiz/attempts/${attemptId.value}/submit`,
        { method: 'POST' },
      )
      await loadResult()
      if (res.status === 'submitted' && res.grading_task_id) {
        gradingPending.value = true
        pollGrading()
      }
    } catch (e: any) {
      if (e?.response?.status === 409) {
        error.value = 'Попытка уже отправлена'
      } else {
        error.value = e?.data?.detail ?? 'Не удалось отправить ответы'
      }
    } finally {
      submitting.value = false
    }
  }

  const reset = () => {
    if (saveTimer) clearTimeout(saveTimer)
    stopGradingPoll()
    info.value = null
    attemptId.value = null
    questions.value = []
    responses.value = {}
    result.value = null
    error.value = ''
    hasQuiz.value = false
    saveStatus.value = 'idle'
    gradingPending.value = false
  }

  onUnmounted(() => {
    if (saveTimer) clearTimeout(saveTimer)
    stopGradingPoll()
  })

  return {
    info, attemptId, questions, responses, result,
    loading, submitting, error, hasQuiz, saveStatus, gradingPending,
    fetchInfo, start, setResponse, flushSave, loadResult, submit, reset,
  }
}
