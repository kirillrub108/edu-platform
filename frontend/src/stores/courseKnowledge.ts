import { defineStore } from 'pinia'
import type { KnowledgeMaterial } from '~/stores/lessonKnowledge'
import { knowledgeErrorMessage } from '~/stores/lessonKnowledge'

/** Note METADATA only — the body is fetched per lesson (see the backend DTO). */
export interface CourseKnowledgeNote {
  id: string
  lesson_id: string
  title: string
  order: number
  updated_at: string
}

export interface CourseKnowledgeLesson {
  id: string
  title: string
  order: number
  content_type: string
  materials: KnowledgeMaterial[]
  notes: CourseKnowledgeNote[]
}

export interface CourseKnowledgeModule {
  id: string
  title: string
  order: number
  lessons: CourseKnowledgeLesson[]
}

export interface CourseKnowledgeTree {
  course_id: string
  course_title: string
  can_edit: boolean
  modules: CourseKnowledgeModule[]
}

export const useCourseKnowledgeStore = defineStore('courseKnowledge', () => {
  const { apiFetch } = useApi()

  const tree = ref<CourseKnowledgeTree | null>(null)
  const courseId = ref<string | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const fetchTree = async (id: string): Promise<void> => {
    loading.value = true
    error.value = null
    try {
      tree.value = await apiFetch<CourseKnowledgeTree>(`/courses/${id}/knowledge`)
      courseId.value = id
    } catch (err: any) {
      tree.value = null
      error.value = knowledgeErrorMessage(err, 'Не удалось загрузить базу знаний курса')
    } finally {
      loading.value = false
    }
  }

  return { tree, courseId, loading, error, fetchTree }
})
