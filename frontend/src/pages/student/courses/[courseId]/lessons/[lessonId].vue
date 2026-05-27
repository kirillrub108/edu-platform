<script setup lang="ts">
import { CheckCircle } from 'lucide-vue-next'

interface FullLesson {
  id: string
  title: string
  content_type: 'video' | 'text' | 'quiz'
  status: string
  video_url?: string | null
  text_content?: string | null
}

definePageMeta({ layout: 'student', middleware: ['auth'] })

const route = useRoute()
const { apiFetch } = useApi()
const studentStore = useStudentStore()

const courseId = computed(() => route.params.courseId as string)
const lessonId = computed(() => route.params.lessonId as string)

const fullLesson = ref<FullLesson | null>(null)
const loading = ref(true)
const notFound = ref(false)
const isCompleted = ref(false)

// Find the module containing this lesson (for breadcrumbs)
const activeModule = computed(() =>
  studentStore.activeCourse?.modules.find(m => m.lessons.some(l => l.id === lessonId.value))
)

const loadLesson = async () => {
  loading.value = true
  notFound.value = false
  fullLesson.value = null

  try {
    // Ensure course structure is loaded (handles deep links where store is empty)
    if (studentStore.activeCourseId !== courseId.value) {
      await studentStore.fetchCourse(courseId.value)
    }

    // If lessonId is not in this course, redirect to first lesson
    const allLessons = studentStore.activeCourse?.modules.flatMap(m => m.lessons) ?? []
    if (allLessons.length && !allLessons.find(l => l.id === lessonId.value)) {
      const first = allLessons[0]
      await navigateTo(`/student/courses/${courseId.value}/lessons/${first.id}`, { replace: true })
      return
    }

    // Fetch full lesson data (includes signed video_url and text_content)
    fullLesson.value = await apiFetch<FullLesson>(`/students/lessons/${lessonId.value}`)
    isCompleted.value =
      studentStore.activeCourse?.lesson_progress?.[lessonId.value]?.is_completed ?? false
  } catch {
    notFound.value = true
  } finally {
    loading.value = false
  }
}

const markComplete = async () => {
  if (isCompleted.value) return
  try {
    await apiFetch(`/students/lessons/${lessonId.value}/complete`, { method: 'POST' })
    isCompleted.value = true
    // Refresh sidebar progress stats
    await studentStore.fetchCourse(courseId.value)
  } catch {
    // Non-critical: if complete fails, user can retry on next visit
  }
}

/**
 * Called by QuizTaker once it knows whether a quiz exists for this lesson.
 * - No quiz  → auto-complete immediately (video / text opened = done)
 * - Has quiz → wait for quiz-passed event
 */
const onHasQuiz = async (value: boolean) => {
  if (!value && !isCompleted.value) {
    await markComplete()
  }
}

/**
 * Called by QuizTaker when the attempt is graded and passed === true.
 */
const onQuizPassed = async () => {
  await markComplete()
}

// Reload when navigating between lessons within the same course
watch(lessonId, loadLesson)

onMounted(loadLesson)
</script>

<template>
  <div class="p-6 lg:p-8">
    <div v-if="loading" class="text-gray-500">Загрузка…</div>

    <div v-else-if="notFound" class="text-gray-500">Урок не найден.</div>

    <template v-else-if="fullLesson">
      <!-- Breadcrumbs -->
      <nav class="text-sm text-gray-400 mb-6 flex items-center gap-1.5 flex-wrap">
        <span>{{ studentStore.activeCourse?.title }}</span>
        <template v-if="activeModule">
          <span class="text-gray-300">›</span>
          <span>{{ activeModule.title }}</span>
        </template>
        <span class="text-gray-300">›</span>
        <span class="text-gray-700 font-medium">{{ fullLesson.title }}</span>
      </nav>

      <!-- Lesson content -->
      <LessonPlayer :lesson="fullLesson" />

      <!-- Completion status (read-only, set automatically) -->
      <div v-if="isCompleted" class="mt-4 inline-flex items-center gap-2 text-emerald-600 text-sm font-medium">
        <CheckCircle class="w-4 h-4" />
        Урок пройден
      </div>

      <!-- Quiz — emits has-quiz and quiz-passed to drive completion logic -->
      <div class="mt-8">
        <QuizTaker
          :lesson-id="lessonId"
          @has-quiz="onHasQuiz"
          @quiz-passed="onQuizPassed"
        />
      </div>
    </template>
  </div>
</template>
