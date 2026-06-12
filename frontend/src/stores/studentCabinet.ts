import { defineStore } from 'pinia'

// ── API response shapes (mirror app/schemas/student.py) ─────────────────────
// Backend endpoints (all GET, behind require_student, prefix /api/v1):
//   /students/dashboard    → DashboardStats
//   /students/quizzes      → StudentQuiz[]
//   /students/results      → StudentResult[]
//   /students/assignments  → StudentAssignment[]
// Course list reuses the existing useStudentStore (/students/my-courses).

export interface NearestDeadline {
  assignment_id: string
  title: string
  course_title: string
  due_at: string
}

export interface DashboardStats {
  enrolled_courses: number
  completed_assignments: number
  average_score: number | null
  nearest_deadline: NearestDeadline | null
}

export interface StudentQuiz {
  lesson_id: string
  course_id: string
  title: string
  course_title: string
  best_score: number | null
  is_passed: boolean
  attempts_allowed: number | null
}

export interface StudentResult {
  attempt_id: string
  lesson_id: string
  course_id: string
  title: string
  course_title: string
  date: string
  score: number | null
  passed: boolean | null
  status: string
}

export interface StudentAssignment {
  assignment_id: string
  lesson_id: string
  course_id: string
  title: string
  course_title: string
  due_at: string | null
  max_points: number
  submission_status: string | null
  score: number | null
}

export const useStudentCabinetStore = defineStore('studentCabinet', () => {
  const { apiFetch } = useApi()

  // Mobile sidebar drawer state (shared by the layout + StudentSidebar).
  const sidebarOpen = ref(false)

  const dashboard = ref<DashboardStats | null>(null)
  const dashboardLoading = ref(false)
  const dashboardError = ref<string | null>(null)

  const quizzes = ref<StudentQuiz[]>([])
  const quizzesLoading = ref(false)
  const quizzesError = ref<string | null>(null)

  const results = ref<StudentResult[]>([])
  const resultsLoading = ref(false)
  const resultsError = ref<string | null>(null)

  const assignments = ref<StudentAssignment[]>([])
  const assignmentsLoading = ref(false)
  const assignmentsError = ref<string | null>(null)

  const fetchDashboard = async () => {
    dashboardLoading.value = true
    dashboardError.value = null
    try {
      dashboard.value = await apiFetch<DashboardStats>('/students/dashboard')
    } catch {
      dashboardError.value = 'Не удалось загрузить дашборд. Попробуйте ещё раз.'
    } finally {
      dashboardLoading.value = false
    }
  }

  const fetchQuizzes = async () => {
    quizzesLoading.value = true
    quizzesError.value = null
    try {
      quizzes.value = await apiFetch<StudentQuiz[]>('/students/quizzes')
    } catch {
      quizzesError.value = 'Не удалось загрузить тесты. Попробуйте ещё раз.'
    } finally {
      quizzesLoading.value = false
    }
  }

  const fetchResults = async () => {
    resultsLoading.value = true
    resultsError.value = null
    try {
      results.value = await apiFetch<StudentResult[]>('/students/results')
    } catch {
      resultsError.value = 'Не удалось загрузить результаты. Попробуйте ещё раз.'
    } finally {
      resultsLoading.value = false
    }
  }

  const fetchAssignments = async () => {
    assignmentsLoading.value = true
    assignmentsError.value = null
    try {
      assignments.value = await apiFetch<StudentAssignment[]>('/students/assignments')
    } catch {
      assignmentsError.value = 'Не удалось загрузить задания. Попробуйте ещё раз.'
    } finally {
      assignmentsLoading.value = false
    }
  }

  return {
    sidebarOpen,
    dashboard,
    dashboardLoading,
    dashboardError,
    quizzes,
    quizzesLoading,
    quizzesError,
    results,
    resultsLoading,
    resultsError,
    assignments,
    assignmentsLoading,
    assignmentsError,
    fetchDashboard,
    fetchQuizzes,
    fetchResults,
    fetchAssignments,
  }
})
