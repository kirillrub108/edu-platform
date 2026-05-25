import { defineStore } from 'pinia'

export interface QuizQuestion {
  id: string
  question: string
  options: string[]
  order: number
}

export interface QuizQuestionResult {
  question_id: string
  correct: boolean
  correct_index: number
}

export interface QuizResult {
  score: number
  correct_count: number
  total: number
  passed: boolean
  questions: QuizQuestionResult[]
}

export const useQuizStore = defineStore('quiz', () => {
  const { apiFetch } = useApi()

  const lessonId = ref<string | null>(null)
  const questions = ref<QuizQuestion[]>([])
  const selectedAnswers = ref<Record<string, number>>({})
  const result = ref<QuizResult | null>(null)
  const loading = ref(false)
  const submitting = ref(false)
  const error = ref<string | null>(null)
  const hasQuiz = ref(false)

  const allAnswered = computed(
    () =>
      questions.value.length > 0 &&
      questions.value.every((q) => q.id in selectedAnswers.value),
  )

  const fetchQuestions = async (id: string) => {
    lessonId.value = id
    questions.value = []
    selectedAnswers.value = {}
    result.value = null
    error.value = null
    hasQuiz.value = false
    loading.value = true
    try {
      const data = await apiFetch<QuizQuestion[]>(`/students/lessons/${id}/quiz`)
      questions.value = data
      hasQuiz.value = data.length > 0
    } catch (e: any) {
      if (e?.response?.status === 404) {
        hasQuiz.value = false
      } else if (e?.response?.status !== 403) {
        error.value = 'Не удалось загрузить вопросы'
      }
    } finally {
      loading.value = false
    }
  }

  const submitAnswers = async () => {
    if (!lessonId.value) return
    submitting.value = true
    error.value = null
    try {
      const answers = Object.entries(selectedAnswers.value).map(
        ([question_id, selected_index]) => ({ question_id, selected_index }),
      )
      result.value = await apiFetch<QuizResult>(
        `/students/lessons/${lessonId.value}/quiz`,
        { method: 'POST', body: { answers } },
      )
    } catch (e: any) {
      if (e?.response?.status === 409) {
        error.value = 'Сначала завершите просмотр урока'
      } else {
        error.value = 'Ошибка при отправке ответов'
      }
    } finally {
      submitting.value = false
    }
  }

  const selectAnswer = (questionId: string, index: number) => {
    selectedAnswers.value = { ...selectedAnswers.value, [questionId]: index }
  }

  const reset = () => {
    lessonId.value = null
    questions.value = []
    selectedAnswers.value = {}
    result.value = null
    loading.value = false
    submitting.value = false
    error.value = null
    hasQuiz.value = false
  }

  return {
    lessonId,
    questions,
    selectedAnswers,
    result,
    loading,
    submitting,
    error,
    hasQuiz,
    allAnswered,
    fetchQuestions,
    submitAnswers,
    selectAnswer,
    reset,
  }
})
