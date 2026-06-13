<script setup lang="ts">
import { Menu, ArrowLeft, Play, FileText, HelpCircle, CheckCircle, Circle } from 'lucide-vue-next'

const route = useRoute()
const studentStore = useStudentStore()

const courseId = computed(() => route.params.courseId as string | undefined)
const lessonId = computed(() => route.params.lessonId as string | undefined)

// Sidebar shows lesson list when inside a course URL
const mode = computed(() => (courseId.value ? 'lessons' : 'courses'))

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
  studentStore.activeCourse?.lesson_progress?.[id]?.is_completed ?? false

const navigateAndClose = (to: string) => {
  studentStore.sidebarOpen = false
  navigateTo(to)
}

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
  if (id && studentStore.activeCourseId !== id) {
    await studentStore.fetchCourse(id)
  }
}, { immediate: true })

onMounted(async () => {
  await studentStore.fetchCourses()
})
</script>

<template>
  <div class="flex flex-col h-screen overflow-hidden">
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
              class="flex items-center gap-1.5 text-sm text-gray-500 hover:text-violet-700 mb-3 transition"
              @click="navigateAndClose('/student/dashboard')"
            >
              <ArrowLeft class="w-4 h-4" />
              Мои курсы
            </button>

            <template v-if="studentStore.activeCourse">
              <div class="text-sm font-bold text-gray-900 px-2 mb-2">
                {{ studentStore.activeCourse.title }}
              </div>

              <div
                v-for="mod in studentStore.activeCourse.modules"
                :key="mod.id"
                class="mb-3"
              >
                <div class="text-xs font-semibold text-gray-500 uppercase tracking-wide px-2 mb-1">
                  {{ mod.title }}
                </div>
                <ul class="space-y-0.5">
                  <li v-for="lesson in mod.lessons" :key="lesson.id">
                    <button
                      class="w-full text-left flex items-center gap-2 px-2 py-2 rounded-lg text-sm transition"
                      :class="lessonId === lesson.id
                        ? 'bg-violet-50 text-violet-700 font-medium'
                        : 'text-gray-700 hover:bg-gray-50'"
                      @click="navigateAndClose(`/student/courses/${courseId}/lessons/${lesson.id}`)"
                    >
                      <component :is="lessonIcon(lesson.content_type)" class="w-3.5 h-3.5 flex-shrink-0" />
                      <span class="flex-1 truncate">{{ lesson.title }}</span>
                      <CheckCircle
                        v-if="isLessonComplete(lesson.id)"
                        class="w-3.5 h-3.5 flex-shrink-0 text-emerald-500"
                      />
                      <Circle v-else class="w-3.5 h-3.5 flex-shrink-0 text-gray-300" />
                    </button>
                  </li>
                </ul>
              </div>

              <p v-if="!studentStore.activeCourse.modules?.length" class="text-sm text-gray-500 text-center py-6">
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
