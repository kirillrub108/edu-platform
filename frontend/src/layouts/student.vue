<script setup lang="ts">
import { Menu, ArrowLeft, Play, FileText, HelpCircle, CheckCircle, Circle, Eye, LogOut } from 'lucide-vue-next'

const route = useRoute()
const studentStore = useStudentStore()
const previewStore = usePreviewStore()

// Teacher «view as student» preview reuses this layout under /courses/:id/preview.
const isPreview = computed(() => String(route.name ?? '').startsWith('courses-id-preview'))

const courseId = computed(() =>
  isPreview.value ? (route.params.id as string) : (route.params.courseId as string | undefined),
)
const lessonId = computed(() => route.params.lessonId as string | undefined)

// Sidebar shows lesson list when inside a course URL
const mode = computed(() => (courseId.value ? 'lessons' : 'courses'))

const exitPreview = async () => {
  const target = previewStore.entryPoint ?? `/courses/${courseId.value}`
  previewStore.reset() // dry-run progress is wiped on exit
  await navigateTo(target)
}

// Remember where the teacher entered preview from (?from=<path> on any preview
// URL) — the exit button returns there. Fallback: the course editor page.
watch(
  [isPreview, () => route.query.from],
  () => {
    if (!isPreview.value) return
    const from = route.query.from
    if (typeof from === 'string' && from.startsWith('/')) {
      previewStore.setEntryPoint(from)
    } else if (!previewStore.entryPoint && courseId.value) {
      previewStore.setEntryPoint(`/courses/${courseId.value}`)
    }
  },
  { immediate: true },
)

const enrollCode = ref('')
const enrolling = ref(false)

const handleEnroll = async () => {
  if (!enrollCode.value.trim() || enrolling.value) return
  enrolling.value = true
  try {
    await studentStore.enroll(enrollCode.value.trim())
    enrollCode.value = ''
  } finally {
    enrolling.value = false
  }
}

const gradients = [
  'from-violet-500 to-fuchsia-500',
  'from-indigo-500 to-purple-500',
  'from-purple-500 to-fuchsia-500',
  'from-violet-600 to-indigo-500',
]
const gradientClass = (idx: number) => `bg-gradient-to-r ${gradients[idx % gradients.length]}`

const lessonIcon = (contentType: string) => {
  if (contentType === 'video') return Play
  if (contentType === 'text') return FileText
  return HelpCircle
}

const isLessonComplete = (id: string) =>
  isPreview.value
    ? previewStore.isCompleted(id)
    : studentStore.activeCourse?.lesson_progress?.[id]?.is_completed ?? false

const navigateAndClose = (to: string) => {
  studentStore.sidebarOpen = false
  navigateTo(to)
}

const lessonLink = (id: string) =>
  isPreview.value
    ? `/courses/${courseId.value}/preview/lessons/${id}`
    : `/student/courses/${courseId.value}/lessons/${id}`

// Unified sidebar tree: student store nodes, or the preview store's annotated
// tree (drafts included — hidden-from-student nodes are badged and dimmed).
interface SidebarLesson {
  id: string
  title: string
  content_type: string
  hidden: boolean
}
interface SidebarModule {
  id: string
  title: string
  hidden: boolean
  lessons: SidebarLesson[]
}

const sidebarCourseTitle = computed(() =>
  isPreview.value ? previewStore.course?.title : studentStore.activeCourse?.title,
)

const sidebarModules = computed<SidebarModule[]>(() => {
  if (isPreview.value) {
    return (previewStore.course?.modules ?? []).map((m) => ({
      id: m.id,
      title: m.title,
      hidden: !m.visible_to_student,
      lessons: m.lessons.map((l) => ({
        id: l.id,
        title: l.title,
        content_type: l.content_type,
        hidden: !l.visible_to_student,
      })),
    }))
  }
  return (studentStore.activeCourse?.modules ?? []).map((m) => ({
    id: m.id,
    title: m.title,
    hidden: false,
    lessons: m.lessons.map((l) => ({
      id: l.id,
      title: l.title,
      content_type: l.content_type,
      hidden: false,
    })),
  }))
})

const sidebarReady = computed(() =>
  isPreview.value ? !!previewStore.course : !!studentStore.activeCourse,
)

// Clicking a course pre-fetches it and navigates directly to the first lesson URL
const courseClickLoading = ref(false)
const handleCourseClick = async (id: string) => {
  if (courseClickLoading.value) return
  courseClickLoading.value = true
  studentStore.sidebarOpen = false
  try {
    await studentStore.fetchCourse(id)
    const first = studentStore.activeCourse?.modules?.[0]?.lessons?.[0]
    if (first) {
      navigateTo(`/student/courses/${id}/lessons/${first.id}`)
    }
  } finally {
    courseClickLoading.value = false
  }
}

// Load sidebar lesson list when entering a course route
watch(courseId, async (id) => {
  if (!id) return
  if (isPreview.value) {
    if (previewStore.courseId !== id) await previewStore.fetchCourse(id)
    return
  }
  if (studentStore.activeCourseId !== id) {
    await studentStore.fetchCourse(id)
  }
}, { immediate: true })

onMounted(async () => {
  // Student-only endpoints — a previewing teacher would just get 403s.
  if (!isPreview.value) await studentStore.fetchCourses()
})
</script>

<template>
  <div class="flex flex-col h-screen overflow-hidden">
    <!-- Preview banner: fixed part of the layout, cannot be dismissed -->
    <div
      v-if="isPreview"
      class="flex-shrink-0 bg-amber-400 text-amber-950 text-sm"
    >
      <div class="flex items-center gap-3 px-4 py-2 flex-wrap">
        <Eye class="w-4 h-4 shrink-0" />
        <span class="font-medium flex-1 min-w-48">
          Режим предпросмотра — вы видите курс как студент. Ответы и прогресс не сохраняются.
        </span>
        <button
          type="button"
          class="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg bg-amber-950/10 hover:bg-amber-950/20 font-medium transition"
          @click="exitPreview"
        >
          <LogOut class="w-3.5 h-3.5" />
          Выйти из предпросмотра
        </button>
      </div>
      <div
        v-if="previewStore.course && !previewStore.course.is_published"
        class="px-4 py-1.5 bg-amber-100 text-amber-800 text-xs border-t border-amber-200"
      >
        Курс не опубликован: он не виден в каталоге и записаться на него нельзя.
        Уже записанные студенты сохраняют доступ к опубликованным урокам.
      </div>
    </div>

    <!-- Shared top navbar (same as teacher) -->
    <AppHeader />

    <!-- Content row: sidebar + main -->
    <div class="flex flex-1 overflow-hidden">
      <!-- Mobile backdrop -->
      <div
        v-if="studentStore.sidebarOpen"
        class="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm lg:hidden"
        @click="studentStore.sidebarOpen = false"
      />

      <!-- Sidebar: fixed on mobile, static on desktop -->
      <aside
        class="fixed inset-y-0 left-0 z-50 w-72 bg-white border-r border-gray-100 flex flex-col
               transition-transform duration-200 lg:static lg:translate-x-0"
        :class="studentStore.sidebarOpen ? 'translate-x-0' : '-translate-x-full'"
      >
        <div class="flex-1 overflow-y-auto p-3 space-y-1">

          <!-- ── COURSES MODE ───────────────────────────────── -->
          <template v-if="mode === 'courses'">
            <form class="mb-3" @submit.prevent="handleEnroll">
              <div class="flex gap-2">
                <input
                  v-model="enrollCode"
                  placeholder="Код доступа"
                  class="flex-1 min-w-0 border border-gray-200 rounded-lg px-3 py-2 text-sm
                         focus:outline-none focus:border-violet-400"
                />
                <button
                  type="submit"
                  :disabled="enrolling"
                  class="px-3 py-2 bg-violet-600 text-white rounded-lg text-sm hover:bg-violet-700
                         transition whitespace-nowrap disabled:opacity-50"
                >
                  Записаться
                </button>
              </div>
            </form>

            <div
              v-for="c in studentStore.courses"
              :key="c.id"
              class="rounded-xl overflow-hidden border border-gray-100 hover:border-violet-200
                     transition cursor-pointer group"
              :class="courseId === c.id ? 'ring-2 ring-violet-400' : ''"
              @click="handleCourseClick(c.id)"
            >
              <div :class="['h-1.5', gradientClass(c.gradient_idx ?? 0)]" />
              <div class="px-3 py-2.5">
                <div class="text-sm font-medium text-gray-900 line-clamp-1 group-hover:text-violet-700 transition">
                  {{ c.title }}
                </div>
                <template v-if="studentStore.courseStats[c.id]">
                  <div class="text-xs text-gray-500 mt-0.5">
                    {{ studentStore.courseStats[c.id].completed }}/{{ studentStore.courseStats[c.id].total }} уроков
                  </div>
                  <div v-if="studentStore.courseStats[c.id].total" class="mt-1.5 h-1 bg-gray-100 rounded-full overflow-hidden">
                    <div
                      class="h-full bg-violet-500 rounded-full transition-all"
                      :style="{ width: `${Math.round((studentStore.courseStats[c.id].completed / studentStore.courseStats[c.id].total) * 100)}%` }"
                    />
                  </div>
                </template>
              </div>
            </div>

            <p v-if="!studentStore.courses.length" class="text-sm text-gray-500 text-center py-6">
              Нет записей
            </p>
          </template>

          <!-- ── LESSONS MODE ───────────────────────────────── -->
          <template v-else>
            <button
              v-if="isPreview"
              class="flex items-center gap-1.5 text-sm text-gray-500 hover:text-violet-700 mb-3 transition"
              @click="exitPreview"
            >
              <ArrowLeft class="w-4 h-4" />
              Выйти из предпросмотра
            </button>
            <button
              v-else
              class="flex items-center gap-1.5 text-sm text-gray-500 hover:text-violet-700 mb-3 transition"
              @click="navigateAndClose('/student/dashboard')"
            >
              <ArrowLeft class="w-4 h-4" />
              Мои курсы
            </button>

            <template v-if="sidebarReady">
              <div class="text-sm font-bold text-gray-900 px-2 mb-2">
                {{ sidebarCourseTitle }}
              </div>

              <div
                v-for="mod in sidebarModules"
                :key="mod.id"
                class="mb-3"
              >
                <div
                  class="text-xs font-semibold uppercase tracking-wide px-2 mb-1 flex items-center gap-1.5"
                  :class="mod.hidden ? 'text-gray-400' : 'text-gray-500'"
                >
                  <span class="truncate">{{ mod.title }}</span>
                  <span
                    v-if="mod.hidden"
                    class="normal-case tracking-normal text-[10px] px-1.5 py-0.5 rounded-full font-medium bg-amber-100 text-amber-700 shrink-0"
                  >Студент не увидит</span>
                </div>
                <ul class="space-y-0.5">
                  <li v-for="lesson in mod.lessons" :key="lesson.id">
                    <button
                      class="w-full text-left flex items-center gap-2 px-2 py-2 rounded-lg text-sm transition"
                      :class="[
                        lessonId === lesson.id
                          ? 'bg-violet-50 text-violet-700 font-medium'
                          : 'text-gray-700 hover:bg-gray-50',
                        lesson.hidden && 'opacity-50',
                      ]"
                      @click="navigateAndClose(lessonLink(lesson.id))"
                    >
                      <component :is="lessonIcon(lesson.content_type)" class="w-3.5 h-3.5 flex-shrink-0" />
                      <span class="flex-1 truncate">{{ lesson.title }}</span>
                      <span
                        v-if="lesson.hidden"
                        class="text-[10px] px-1.5 py-0.5 rounded-full font-medium bg-amber-100 text-amber-700 shrink-0"
                        title="Скрыто от студентов: не опубликован урок или его модуль"
                      >Студент не увидит</span>
                      <CheckCircle
                        v-if="isLessonComplete(lesson.id)"
                        class="w-3.5 h-3.5 flex-shrink-0 text-emerald-500"
                      />
                      <Circle v-else class="w-3.5 h-3.5 flex-shrink-0 text-gray-300" />
                    </button>
                  </li>
                </ul>
              </div>

              <p v-if="!sidebarModules.length" class="text-sm text-gray-500 text-center py-6">
                Уроков пока нет
              </p>
            </template>
            <div v-else class="text-sm text-gray-500 text-center py-6">Загрузка…</div>
          </template>

        </div>
      </aside>

      <!-- Main content area -->
      <div class="flex-1 flex flex-col overflow-hidden">
        <!-- Mobile sub-header: sidebar toggle -->
        <div class="lg:hidden h-12 flex-shrink-0 bg-white border-b border-gray-100 flex items-center px-4">
          <button
            class="p-1.5 rounded-lg text-gray-600 hover:bg-gray-100 transition"
            @click="studentStore.sidebarOpen = true"
          >
            <Menu class="w-5 h-5" />
          </button>
        </div>

        <main class="flex-1 overflow-y-auto bg-transparent">
          <slot />
        </main>
      </div>
    </div>
  </div>
</template>
