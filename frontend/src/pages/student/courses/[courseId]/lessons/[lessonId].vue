<script setup lang="ts">
import { CheckCircle, MessageSquare, X } from 'lucide-vue-next'
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
const router = useRouter()
const { apiFetch } = useApi()
const studentStore = useStudentStore()
const auth = useAuthStore()
const assignmentsStore = useAssignmentsStore()
const commentsStore = useCommentsStore()

const courseId = computed(() => route.params.courseId as string)
const lessonId = computed(() => route.params.lessonId as string)

const fullLesson = ref<FullLesson | null>(null)
const loading = ref(true)
const notFound = ref(false)
const isCompleted = ref(false)

// Quiz status surfaced by QuizTaker's existing emits — no extra request.
const hasQuiz = ref(false)
const quizPassed = ref(false)

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

const onVideoUrlExpired = async () => {
  try {
    fullLesson.value = await apiFetch<FullLesson>(`/students/lessons/${lessonId.value}`)
  } catch { /* non-critical — stale URL remains until next navigation */ }
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
  hasQuiz.value = value
  if (!value && !isCompleted.value) {
    await markComplete()
  }
}

const onQuizPassed = async () => {
  quizPassed.value = true
  await markComplete()
}

// ── Tab state (query-driven, mirrors the teacher lesson page) ──────────────────
const VALID_TABS = ['lesson', 'quiz', 'assignments'] as const
type TabId = (typeof VALID_TABS)[number]

const lessonBadge = computed(() =>
  isCompleted.value ? { text: 'Пройден', tone: 'bg-emerald-100 text-emerald-700' } : null,
)

const quizBadge = computed(() => {
  if (!hasQuiz.value) return null
  return quizPassed.value
    ? { text: 'Сдан', tone: 'bg-emerald-100 text-emerald-700' }
    : { text: 'Не сдан', tone: 'bg-amber-100 text-amber-700' }
})

// Aggregate over assignments already loaded by AssignmentsStudentPanel.
const assignmentBadge = computed(() => {
  const items = assignmentsStore.studentState(lessonId.value).items
  if (!items.length) return null
  const done = (s?: string) => s === 'submitted' || s === 'graded' || s === 'returned'
  const allDone = items.every((a) => done(a.my_submission?.status))
  return allDone
    ? { text: 'Сдано', tone: 'bg-emerald-100 text-emerald-700' }
    : { text: 'Не начато', tone: 'bg-gray-100 text-gray-500' }
})

const tabItems = computed(() => [
  { id: 'lesson', label: 'Урок', badge: lessonBadge.value },
  { id: 'quiz', label: 'Тест', badge: quizBadge.value },
  { id: 'assignments', label: 'Задания', badge: assignmentBadge.value },
])

const activeTab = computed<TabId>(() => {
  const t = route.query.tab as string
  return (VALID_TABS as readonly string[]).includes(t) ? (t as TabId) : 'lesson'
})

// Normalize a missing/invalid ?tab without adding a history entry.
watch(
  () => route.query.tab,
  () => {
    if (route.query.tab !== activeTab.value) {
      router.replace({ query: { ...route.query, tab: activeTab.value } })
    }
  },
  { immediate: true },
)

const setTab = (id: string) => {
  router.replace({ query: { ...route.query, tab: id } })
}

// ── Comments (mobile drawer toggle + unread-agnostic count badge) ──────────────
const commentsOpen = ref(false)
const commentsTotal = computed(() => commentsStore.getState(lessonId.value).total)

watch(lessonId, () => {
  commentsOpen.value = false
  loadLesson()
})
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
      <!-- Main column: breadcrumb + sticky tabs + tab panels -->
      <div class="min-w-0">
        <nav class="text-sm text-gray-500 flex items-center gap-1.5 flex-wrap mb-4">
          <span>{{ studentStore.activeCourse?.title }}</span>
          <template v-if="activeModule">
            <span class="text-gray-300">›</span>
            <span>{{ activeModule.title }}</span>
          </template>
          <span class="text-gray-300">›</span>
          <span class="text-gray-700 font-medium">{{ fullLesson.title }}</span>
        </nav>

        <!-- Sticky tab bar — bg matches the layout's gray-50 scroll area so
             content scrolls cleanly underneath it. -->
        <div class="sticky top-0 z-20 bg-gray-50/95 backdrop-blur-sm pt-1">
          <UiTabs
            :model-value="activeTab"
            :tabs="tabItems"
            @update:model-value="setTab"
          />
        </div>

        <!-- Урок -->
        <div
          v-show="activeTab === 'lesson'"
          id="tabpanel-lesson"
          role="tabpanel"
          aria-labelledby="tab-lesson"
          class="space-y-5"
        >
          <div class="mx-auto w-full max-w-[720px]">
            <LessonPlayer :lesson="fullLesson" @video-url-expired="onVideoUrlExpired" />
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
        </div>

        <!-- Тест — kept mounted via v-show so QuizTaker's emits keep the badge fresh -->
        <div
          v-show="activeTab === 'quiz'"
          id="tabpanel-quiz"
          role="tabpanel"
          aria-labelledby="tab-quiz"
        >
          <QuizTaker
            :lesson-id="lessonId"
            @has-quiz="onHasQuiz"
            @quiz-passed="onQuizPassed"
          />
        </div>

        <!-- Задания — kept mounted so its fetched state feeds the badge -->
        <div
          v-show="activeTab === 'assignments'"
          id="tabpanel-assignments"
          role="tabpanel"
          aria-labelledby="tab-assignments"
        >
          <AssignmentsStudentPanel :lesson-id="lessonId" />
        </div>
      </div>

      <!-- Mobile drawer backdrop -->
      <div
        v-if="commentsOpen"
        class="lg:hidden fixed inset-0 z-40 bg-black/40 backdrop-blur-sm"
        @click="commentsOpen = false"
      />

      <!-- Comments: desktop = sticky right column; mobile = slide-over drawer.
           Single CommentsPanel instance (one fetch/poll) repositioned via CSS. -->
      <aside
        class="fixed inset-y-0 right-0 z-50 w-[88%] max-w-sm p-4 bg-gray-50 shadow-2xl flex flex-col transition-transform duration-200
               lg:inset-auto lg:z-auto lg:w-auto lg:max-w-none lg:p-0 lg:bg-transparent lg:shadow-none lg:translate-x-0
               lg:sticky lg:top-4 lg:max-h-[calc(100vh-7rem)]"
        :class="commentsOpen ? 'translate-x-0' : 'translate-x-full lg:translate-x-0'"
      >
        <div class="lg:hidden flex justify-end mb-2">
          <button
            type="button"
            class="p-1.5 rounded-lg text-gray-500 hover:bg-gray-100 transition"
            aria-label="Закрыть комментарии"
            @click="commentsOpen = false"
          >
            <X class="w-5 h-5" />
          </button>
        </div>

        <CommentsPanel
          :lesson-id="lessonId"
          :can-delete="canDeleteComment"
          class="flex-1 min-h-0"
        />
      </aside>

      <!-- Mobile comments trigger (FAB) with count badge -->
      <button
        type="button"
        class="lg:hidden fixed bottom-5 right-5 z-30 inline-flex items-center gap-2 rounded-full bg-violet-600 text-white pl-4 pr-5 py-3 shadow-lg hover:bg-violet-700 transition"
        @click="commentsOpen = true"
      >
        <MessageSquare class="w-5 h-5" />
        <span class="text-sm font-medium">Комментарии</span>
        <span
          v-if="commentsTotal"
          class="inline-flex items-center justify-center min-w-5 h-5 px-1.5 rounded-full bg-white/25 text-xs font-semibold"
        >
          {{ commentsTotal }}
        </span>
      </button>
    </div>
  </div>
</template>
