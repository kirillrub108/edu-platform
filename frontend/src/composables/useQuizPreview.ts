/**
 * Dry-run quiz lifecycle for the teacher «view as student» preview. Mirrors
 * the surface of useQuizAttempt so QuizTaker can swap composables via the
 * `preview` prop, but never creates attempts, autosaves or enqueues grading:
 * questions (with answers) come from the owner endpoints and auto-gradable
 * types are checked on the client (utils/quizGrading). Open questions show
 * the reference answer / rubric instead of LLM feedback.
 */

import type { StudentQuestion, QuizInfo, AttemptResult, AnswerResult } from '~/composables/useQuizAttempt'
import {
  gradeAutoResponse,
  isAutoGradable,
  toStudentPayload,
  type QuizQuestionType,
} from '~/utils/quizGrading'

interface TeacherQuizRead {
  id: string
  lesson_id: string
  status: 'draft' | 'published'
  attempts_allowed: number | null
  pass_threshold: string
  show_answers: boolean
  shuffle: boolean
}

interface TeacherQuestionRead {
  id: string
  quiz_id: string
  type: QuizQuestionType
  payload: Record<string, any>
  weight: string
  order: number
}

export function useQuizPreview(lessonId: Readonly<Ref<string>>) {
  const { apiFetch } = useApi()

  const info = ref<QuizInfo | null>(null)
  const attemptId = ref<string | null>(null)
  const questions = ref<StudentQuestion[]>([])
  const responses = ref<Record<string, any>>({})
  const result = ref<AttemptResult | null>(null)
  const loading = ref(false)
  const submitting = ref(false)
  const error = ref('')
  const hasQuiz = ref(false)
  const saveStatus = ref<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const gradingPending = ref(false)
  // Preview-only extra: quiz publication status for the «Студент не увидит» badge.
  const quizStatus = ref<'draft' | 'published' | null>(null)

  let teacherQuestions: TeacherQuestionRead[] = []

  const fetchInfo = async (): Promise<boolean> => {
    error.value = ''
    loading.value = true
    try {
      const quiz = await apiFetch<TeacherQuizRead>(`/lessons/${lessonId.value}/quiz`)
      quizStatus.value = quiz.status
      info.value = {
        quiz_id: quiz.id,
        pass_threshold: quiz.pass_threshold,
        attempts_allowed: quiz.attempts_allowed,
        attempts_used: 0,
        show_answers: quiz.show_answers,
        shuffle: quiz.shuffle,
        in_progress_attempt_id: null,
      }
      hasQuiz.value = true
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
      teacherQuestions = await apiFetch<TeacherQuestionRead[]>(
        `/lessons/${lessonId.value}/quiz/questions`,
      )
      questions.value = teacherQuestions.map((q) => ({
        id: q.id,
        type: q.type,
        payload: toStudentPayload(q.type, q.payload),
        order: q.order,
      }))
      responses.value = {}
      result.value = null
      attemptId.value = 'preview'
    } catch (e: any) {
      error.value = e?.data?.detail ?? 'Не удалось начать попытку'
    }
  }

  const setResponse = (questionId: string, response: any) => {
    responses.value = { ...responses.value, [questionId]: response }
  }

  const submit = async () => {
    submitting.value = true
    error.value = ''
    try {
      const answers: AnswerResult[] = []
      let autoWeight = 0
      let autoCorrectWeight = 0

      for (const q of teacherQuestions) {
        const weight = Number(q.weight) || 0
        const isCorrect = gradeAutoResponse(q.type, q.payload, responses.value[q.id])
        if (isAutoGradable(q.type)) {
          autoWeight += weight
          if (isCorrect) autoCorrectWeight += weight
        }
        answers.push({
          question_id: q.id,
          awarded_score: isCorrect === null ? null : String(isCorrect ? weight : 0),
          max_score: q.weight,
          is_correct: isCorrect,
          needs_review: false,
          graded_by_ai: false,
          llm_feedback: null,
          // Full teacher payload → the result view shows эталон/критерии.
          correct_payload: q.payload,
        })
      }

      const score = autoWeight > 0 ? autoCorrectWeight / autoWeight : null
      const passed =
        score === null ? null : score >= Number(info.value?.pass_threshold ?? 1)
      const now = new Date().toISOString()

      result.value = {
        attempt_id: 'preview',
        quiz_id: info.value?.quiz_id ?? '',
        attempt_number: 1,
        status: 'graded',
        score: score === null ? null : String(score),
        passed,
        started_at: now,
        submitted_at: now,
        graded_at: now,
        grading_task_id: null,
        ai_graded: false,
        questions: questions.value,
        answers,
      }
    } finally {
      submitting.value = false
    }
  }

  const reset = () => {
    info.value = null
    attemptId.value = null
    questions.value = []
    responses.value = {}
    result.value = null
    error.value = ''
    hasQuiz.value = false
    saveStatus.value = 'idle'
    gradingPending.value = false
    quizStatus.value = null
    teacherQuestions = []
  }

  return {
    info, attemptId, questions, responses, result,
    loading, submitting, error, hasQuiz, saveStatus, gradingPending,
    quizStatus,
    fetchInfo, start, setResponse, submit, reset,
  }
}
