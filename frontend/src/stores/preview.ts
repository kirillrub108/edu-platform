import { defineStore } from 'pinia'

export interface PreviewLessonNode {
  id: string
  title: string
  order: number
  content_type: 'video' | 'text' | 'quiz'
  status: string
  is_published: boolean
  visible_to_student: boolean
}

export interface PreviewModuleNode {
  id: string
  title: string
  order: number
  is_published: boolean
  visible_to_student: boolean
  lessons: PreviewLessonNode[]
}

export interface PreviewCourse {
  id: string
  title: string
  description: string | null
  is_published: boolean
  modules: PreviewModuleNode[]
}

/**
 * Teacher «view as student» preview. Holds the owner-annotated course tree and
 * the DRY-RUN progress: «пройдено» lives only here (in memory) and is wiped on
 * exit/refresh — nothing is ever written to the backend from preview mode.
 */
export const usePreviewStore = defineStore('preview', () => {
  const { apiFetch } = useApi()

  const course = ref<PreviewCourse | null>(null)
  const courseId = ref<string | null>(null)
  const completed = ref<Record<string, boolean>>({})
  // Where the teacher entered preview from — the exit button returns there.
  const entryPoint = ref<string | null>(null)

  const fetchCourse = async (id: string): Promise<void> => {
    course.value = await apiFetch<PreviewCourse>(`/courses/${id}/preview`)
    courseId.value = id
  }

  const markCompleted = (lessonId: string): void => {
    completed.value = { ...completed.value, [lessonId]: true }
  }

  const isCompleted = (lessonId: string): boolean => completed.value[lessonId] === true

  const findLesson = (lessonId: string): PreviewLessonNode | null => {
    for (const mod of course.value?.modules ?? []) {
      const lesson = mod.lessons.find((l) => l.id === lessonId)
      if (lesson) return lesson
    }
    return null
  }

  const findModuleOfLesson = (lessonId: string): PreviewModuleNode | null =>
    course.value?.modules.find((m) => m.lessons.some((l) => l.id === lessonId)) ?? null

  const setEntryPoint = (path: string): void => {
    entryPoint.value = path
  }

  const reset = (): void => {
    course.value = null
    courseId.value = null
    completed.value = {}
    entryPoint.value = null
  }

  return {
    course,
    courseId,
    completed,
    entryPoint,
    fetchCourse,
    markCompleted,
    isCompleted,
    findLesson,
    findModuleOfLesson,
    setEntryPoint,
    reset,
  }
})
