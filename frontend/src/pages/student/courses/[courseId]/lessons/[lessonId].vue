<script setup lang="ts">
import { CheckCircle } from 'lucide-vue-next'
import type { Comment } from '~/stores/comments'

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
const auth = useAuthStore()

const courseId = computed(() => route.params.courseId as string)
const lessonId = computed(() => route.params.lessonId as string)

const fullLesson = ref<FullLesson | null>(null)
const loading = ref(true)
const notFound = ref(false)
const isCompleted = ref(false)

const activeModule = computed(() =>
  studentStore.activeCourse?.modules.find((m) => m.lessons.some((l) => l.id === lessonId.value)),
)

const canDeleteComment = (c: Comment): boolean =>
  !!auth.user && c.author.id === auth.user.id

const loadLesson = async () => {
  loading.value = true
  notFound.value = false
  fullLesson.value = null

  try {
    if (studentStore.activeCourseId !== courseId.value) {
      await studentStore.fetchCourse(courseId.value)
    }

    const allLessons = studentStore.activeCourse?.modules.flatMap((m) => m.lessons) ?? []
    if (allLessons.length && !allLessons.find((l) => l.id === lessonId.value)) {
      const first = allLessons[0]
      await navigateTo(`/student/courses/${courseId.value}/lessons/${first.id}`, {
        replace: true,
      })
      return
    }

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
    await studentStore.fetchCourse(courseId.value)
  } catch {
    /* non-critical */
  }
}

const onHasQuiz = async (value: boolean) => {
  if (!value && !isCompleted.value) {
    await markComplete()
  }
}

const onQuizPassed = async () => {
  await markComplete()
}

watch(lessonId, loadLesson)
onMounted(loadLesson)
</script>

<template>
  <div class="p-4 lg:p-6">
    <div v-if="loading" class="text-gray-500">Загрузка…</div>

    <div v-else-if="notFound" class="text-gray-500">Урок не найден.</div>

    <div
      v-else-if="fullLesson"
      class="lg:grid lg:grid-cols-[minmax(0,1fr)_360px] lg:gap-6"
    >
      <!-- Center column: video + meta + quiz -->
      <div class="space-y-5 min-w-0">
        <nav class="text-sm text-gray-400 flex items-center gap-1.5 flex-wrap">
          <span>{{ studentStore.activeCourse?.title }}</span>
          <template v-if="activeModule">
            <span class="text-gray-300">›</span>
            <span>{{ activeModule.title }}</span>
          </template>
          <span class="text-gray-300">›</span>
          <span class="text-gray-700 font-medium">{{ fullLesson.title }}</span>
        </nav>

        <div class="mx-auto w-full max-w-[720px]">
          <LessonPlayer :lesson="fullLesson" />
        </div>

        <div class="bg-white border border-gray-100 rounded-2xl p-5 space-y-3">
          <h1 class="text-xl font-semibold text-gray-900">{{ fullLesson.title }}</h1>
          <div class="flex items-center gap-3 text-xs">
            <span class="px-2 py-1 rounded-md bg-violet-50 text-violet-700 font-medium">
              {{ activeModule?.title }}
            </span>
            <span
              v-if="isCompleted"
              class="inline-flex items-center gap-1 text-emerald-600 font-medium"
            >
              <CheckCircle class="w-3.5 h-3.5" />
              Урок пройден
            </span>
          </div>
        </div>

        <QuizTaker
          :lesson-id="lessonId"
          @has-quiz="onHasQuiz"
          @quiz-passed="onQuizPassed"
        />
      </div>

      <!-- Right column: comments -->
      <aside
        class="mt-6 lg:mt-0 lg:sticky lg:top-4 lg:max-h-[calc(100vh-7rem)] lg:flex lg:flex-col"
      >
        <CommentsPanel
          :lesson-id="lessonId"
          :can-delete="canDeleteComment"
          class="lg:flex-1 lg:min-h-0"
        />
      </aside>
    </div>
  </div>
</template>
