<script setup lang="ts">
interface LessonProgress {
  effective_score: number | null
  teacher_comment: string | null
  is_completed: boolean
}

interface LessonNode {
  id: string
  title: string
  content_type: 'video' | 'text' | 'quiz'
  status: string
  video_url?: string | null
  text_content?: string | null
}

interface ModuleNode {
  id: string
  title: string
  lessons: LessonNode[]
}

interface CourseWithProgress {
  title: string
  modules: ModuleNode[]
  lesson_progress: Record<string, LessonProgress>
}

const route = useRoute()
const { apiFetch } = useApi()

const course = ref<CourseWithProgress | null>(null)
const activeLesson = ref<LessonNode | null>(null)
const loading = ref(true)
const isCompleted = ref(false)

const lessonIdRef = computed(() => activeLesson.value?.id ?? '')

const lessonProgress = (lessonId: string): LessonProgress | null =>
  course.value?.lesson_progress?.[lessonId] ?? null

const activeProgress = computed<LessonProgress | null>(() =>
  activeLesson.value ? lessonProgress(activeLesson.value.id) : null,
)

const scoreBandClasses = (score: number | null): string => {
  if (score === null) return 'bg-gray-100 text-gray-500'
  if (score >= 80) return 'bg-emerald-50 text-emerald-700'
  if (score >= 60) return 'bg-amber-50 text-amber-700'
  return 'bg-rose-50 text-rose-700'
}

// The course tree returns LessonShort entries — without video_url / text_content.
// To render the player we have to fetch the full lesson via the dedicated
// endpoint (which also signs the video URL for this student).
const loadActiveLesson = async (id: string) => {
  try {
    const full = await apiFetch<LessonNode>(`/students/lessons/${id}`)
    // Guard against a stale response if the user clicked another lesson
    // between dispatching the request and its resolution.
    if (activeLesson.value?.id === id) {
      activeLesson.value = { ...activeLesson.value, ...full }
    }
  } catch {
    // Leave the summary in place; player falls back to "Video status: X".
  }
}

const load = async () => {
  loading.value = true
  try {
    course.value = await apiFetch<CourseWithProgress>(`/students/courses/${route.params.id}`)
    const first = course.value?.modules?.[0]?.lessons?.[0] ?? null
    activeLesson.value = first
    if (first) await loadActiveLesson(first.id)
  } finally {
    loading.value = false
  }
}

const selectLesson = async (lesson: LessonNode) => {
  activeLesson.value = lesson
  isCompleted.value = false
  await loadActiveLesson(lesson.id)
}

const markComplete = async () => {
  if (!activeLesson.value) return
  await apiFetch(`/students/lessons/${activeLesson.value.id}/complete`, { method: 'POST' })
  isCompleted.value = true
}

onMounted(async () => {
  await load()
  await restoreScroll()
})
</script>

<template>
  <div v-if="loading" class="text-gray-500">Загрузка…</div>
  <div v-else-if="course" class="grid grid-cols-1 md:grid-cols-3 gap-6">
    <aside class="md:col-span-1 bg-white border rounded-xl p-3 shadow-soft">
      <h2 class="font-semibold mb-2 text-gray-900">{{ course.title }}</h2>
      <div v-for="m in course.modules" :key="m.id" class="mb-3">
        <div class="text-sm font-medium text-gray-700">{{ m.title }}</div>
        <ul class="mt-1 text-sm">
          <li
            v-for="l in m.lessons"
            :key="l.id"
            class="cursor-pointer px-2 py-1.5 rounded-lg hover:bg-gray-100 flex items-center gap-2"
            :class="{ 'bg-violet-50 text-violet-700 font-medium': activeLesson?.id === l.id }"
            @click="selectLesson(l)"
          >
            <span class="flex-1 truncate">{{ l.title }}</span>
            <span
              v-if="lessonProgress(l.id)?.is_completed && lessonProgress(l.id)?.effective_score !== null"
              :class="['text-xs px-1.5 py-0.5 rounded-md font-medium', scoreBandClasses(lessonProgress(l.id)!.effective_score)]"
            >
              {{ lessonProgress(l.id)!.effective_score!.toFixed(1) }}
            </span>
          </li>
        </ul>
      </div>
    </aside>

    <section class="md:col-span-2 space-y-4">
      <LessonPlayer v-if="activeLesson" :lesson="activeLesson" />

      <!-- Score + comment block for the active lesson, when a grade exists -->
      <div
        v-if="activeProgress?.effective_score !== null && activeProgress?.effective_score !== undefined"
        class="bg-white border border-gray-100 rounded-xl p-4 shadow-soft"
      >
        <div class="flex items-center gap-3">
          <span
            :class="['inline-flex items-center justify-center px-3 py-1.5 rounded-lg text-lg font-semibold', scoreBandClasses(activeProgress.effective_score)]"
          >
            {{ activeProgress.effective_score.toFixed(1) }}
          </span>
          <div class="text-sm text-gray-600">Ваш итоговый балл за этот урок</div>
        </div>
        <div
          v-if="activeProgress.teacher_comment"
          class="mt-3 text-sm text-gray-700 bg-gray-50 border border-gray-100 rounded-lg p-3 whitespace-pre-line"
        >
          <div class="text-xs font-medium text-gray-500 mb-1">Комментарий преподавателя</div>
          {{ activeProgress.teacher_comment }}
        </div>
      </div>

      <button
        v-if="activeLesson && !isCompleted"
        class="px-3 py-1.5 bg-brand text-white rounded-lg text-sm hover:bg-brand-dark transition"
        @click="markComplete"
      >
        Отметить пройденным
      </button>

      <QuizTaker v-if="activeLesson" :lesson-id="lessonIdRef" />
    </section>
  </div>
</template>
