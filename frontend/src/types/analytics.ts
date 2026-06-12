export type QuizLessonSort =
  | 'last_attempt_at'
  | 'attempts_count'
  | 'avg_score'
  | 'pass_rate'
  | 'lesson_title'

export type SortOrder = 'asc' | 'desc'

export interface QuizLessonStats {
  lesson_id: string
  lesson_title: string
  course_id: string
  course_title: string
  module_title: string
  attempts_count: number
  students_count: number
  avg_score: number | null
  pass_rate: number | null
  last_attempt_at: string | null
}

export interface QuizLessonStatsPage {
  items: QuizLessonStats[]
  total: number
  page: number
  page_size: number
}

export interface QuizSubmission {
  student_id: string
  student_email: string
  student_full_name: string | null
  lesson_id: string
  lesson_title: string
  course_title: string
  score: number | null
  is_completed: boolean
  completed_at: string | null
  passed: boolean
}

export interface QuizSubmissionPage {
  items: QuizSubmission[]
  total: number
  page: number
  page_size: number
}

export interface QuizAnalyticsSummary {
  total_quiz_lessons: number
  total_attempts: number
  avg_score: number | null
  pass_rate: number | null
  recent_submissions: QuizSubmission[]
}

export interface CourseOption {
  id: string
  title: string
}

export interface QuizResultOut {
  student_id: string
  student_email: string
  student_full_name: string | null
  progress_id: string | null
  quiz_score: number | null
  is_completed: boolean
  completed_at: string | null
  edited_by_teacher: boolean
  edit_reason: string | null
  attempts: number
}

export interface QuizResultsResponse {
  lesson_id: string
  lesson_title: string
  items: QuizResultOut[]
}

export type AttemptStatus = 'in_progress' | 'submitted' | 'graded'

// GET /lessons/{lessonId}/quiz/attempts — Decimal fields arrive as JSON strings.
export interface TeacherQuizAttempt {
  id: string
  quiz_id: string
  student_id: string
  student_email: string
  student_full_name: string | null
  attempt_number: number
  status: AttemptStatus
  score: string | null
  passed: boolean | null
  submitted_at: string | null
  graded_at: string | null
  has_pending_review: boolean
}

export interface TeacherQuizAnswer {
  id: string
  question_id: string
  question_payload: Record<string, any>
  response: Record<string, any>
  awarded_score: string | null
  max_score: string
  is_correct: boolean | null
  needs_review: boolean
  llm_feedback: string | null
  manually_overridden: boolean
  graded_by_ai: boolean
}

export interface TeacherQuizAttemptDetail extends TeacherQuizAttempt {
  answers: TeacherQuizAnswer[]
  ai_graded: boolean
}
