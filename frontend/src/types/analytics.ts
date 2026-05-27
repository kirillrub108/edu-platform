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
