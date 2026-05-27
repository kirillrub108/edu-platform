import { defineStore } from 'pinia'

interface CourseOut {
  id: string
  title: string
  description?: string | null
  is_published: boolean
  lessons_count?: number
  completed_lessons?: number
  gradient_idx?: number
}

interface LessonNode {
  id: string
  title: string
  content_type: 'video' | 'text' | 'quiz'
  status: string
}

interface ModuleNode {
  id: string
  title: string
  lessons: LessonNode[]
}

interface LessonProgress {
  effective_score: number | null
  teacher_comment: string | null
  is_completed: boolean
}

export interface CourseDetail {
  title: string
  modules: ModuleNode[]
  lesson_progress: Record<string, LessonProgress>
}

export const useStudentStore = defineStore('student', () => {
  const { apiFetch } = useApi()

  const sidebarOpen = ref(false)
  const courses = ref<CourseOut[]>([])
  const activeCourse = ref<CourseDetail | null>(null)
  const activeCourseId = ref<string | null>(null)
  // Lesson stats per course, populated lazily when fetchCourse() is called.
  // CourseOut from /my-courses has no lesson counts, so we derive them from
  // the full detail response that includes modules + lesson_progress.
  const courseStats = ref<Record<string, { total: number; completed: number }>>({})

  const fetchCourses = async () => {
    courses.value = await apiFetch<CourseOut[]>('/students/my-courses')
  }

  const fetchCourse = async (id: string) => {
    activeCourse.value = await apiFetch<CourseDetail>(`/students/courses/${id}`)
    activeCourseId.value = id

    // Cache lesson stats so the sidebar courses list can show X/Y уроков
    const total = activeCourse.value?.modules.flatMap(m => m.lessons).length ?? 0
    const completed = Object.values(activeCourse.value?.lesson_progress ?? {})
      .filter(p => p.is_completed).length
    courseStats.value = { ...courseStats.value, [id]: { total, completed } }
  }

  const enroll = async (code: string) => {
    await apiFetch('/students/enroll', { method: 'POST', body: { access_code: code } })
    await fetchCourses()
  }

  return { sidebarOpen, courses, activeCourse, activeCourseId, courseStats, fetchCourses, fetchCourse, enroll }
})
