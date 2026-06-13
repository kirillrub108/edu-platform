<script setup lang="ts">
import { BookOpen, ClipboardCheck, Award, CalendarClock, Search, ArrowRight } from 'lucide-vue-next'

definePageMeta({ layout: 'student-cabinet', middleware: ['auth', 'student'] })

const cabinet = useStudentCabinetStore()
const student = useStudentStore()

const coursesLoading = ref(false)
const coursesError = ref<string | null>(null)

const dateFmt = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'long',
  hour: '2-digit',
  minute: '2-digit',
})
const formatDate = (iso: string) => dateFmt.format(new Date(iso))

const avgValue = computed(() => {
  const s = cabinet.dashboard?.average_score
  return s === null || s === undefined ? '—' : `${s}%`
})

const progressPct = (c: { completed_lessons: number; lessons_count: number }) =>
  c.lessons_count > 0 ? Math.round((c.completed_lessons / c.lessons_count) * 100) : 0

// Same palette as CourseCard.vue
const gradients = [
  'from-violet-500 via-purple-500 to-fuchsia-500',
  'from-indigo-500 via-violet-500 to-purple-500',
  'from-purple-500 via-fuchsia-500 to-pink-500',
  'from-violet-600 via-indigo-500 to-blue-500',
]
const courseGradient = (idx?: number) => gradients[(idx ?? 0) % gradients.length]

const enrollCode = ref('')
const enrolling = ref(false)
const enrollError = ref<string | null>(null)

const handleEnroll = async () => {
  const code = enrollCode.value.trim()
  if (!code || enrolling.value) return
  enrolling.value = true
  enrollError.value = null
  try {
    await student.enroll(code)
    enrollCode.value = ''
  } catch {
    enrollError.value = 'Курс не найден или код недействителен.'
  } finally {
    enrolling.value = false
  }
}

const loadCourses = async () => {
  coursesLoading.value = true
  coursesError.value = null
  try {
    await student.fetchCourses()
  } catch {
    coursesError.value = 'Не удалось загрузить курсы. Попробуйте ещё раз.'
  } finally {
    coursesLoading.value = false
  }
}

onMounted(() => {
  cabinet.fetchDashboard()
  loadCourses()
})
</script>

<template>
  <div class="max-w-5xl mx-auto p-6 lg:p-8">
    <h1 class="text-2xl font-semibold text-gray-900 mb-8">Дашборд</h1>

    <!-- ── Продолжить обучение ──────────────────────────────────── -->
    <section class="mb-10">
      <div class="flex flex-col sm:flex-row sm:items-center gap-3 mb-4">
        <h2 class="text-base font-semibold text-gray-700">Продолжить обучение</h2>
        <form class="flex gap-2 sm:ml-auto" @submit.prevent="handleEnroll">
          <input
            v-model="enrollCode"
            placeholder="Код доступа"
            class="w-44 border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:border-violet-400"
          />
          <button
            type="submit"
            :disabled="enrolling"
            class="px-3 py-1.5 bg-violet-600 text-white rounded-lg text-sm hover:bg-violet-700 transition whitespace-nowrap disabled:opacity-50"
          >
            Записаться
          </button>
        </form>
      </div>
      <p v-if="enrollError" class="-mt-2 mb-4 text-sm text-red-600">{{ enrollError }}</p>

      <!-- Skeleton -->
      <div v-if="coursesLoading" class="grid gap-4 sm:grid-cols-2">
        <div
          v-for="n in 2"
          :key="n"
          class="bg-white rounded-2xl border border-gray-100 overflow-hidden animate-pulse"
        >
          <div class="h-16 bg-gray-100" />
          <div class="p-5 space-y-3">
            <div class="h-4 w-2/3 bg-gray-100 rounded" />
            <div class="h-3 w-1/3 bg-gray-100 rounded" />
            <div class="h-1.5 w-full bg-gray-100 rounded-full" />
          </div>
        </div>
      </div>

      <!-- Error -->
      <div
        v-else-if="coursesError"
        class="bg-red-50 border border-red-100 text-red-700 rounded-xl px-4 py-3 text-sm flex items-center justify-between gap-4"
      >
        <span>{{ coursesError }}</span>
        <button
          class="px-3 py-1.5 rounded-lg bg-red-600 text-white text-sm hover:bg-red-700 transition flex-shrink-0"
          @click="loadCourses"
        >
          Повторить
        </button>
      </div>

      <!-- Empty state -->
      <div
        v-else-if="!student.courses.length"
        class="bg-white rounded-2xl border border-gray-100 p-8 text-center"
      >
        <div class="w-14 h-14 rounded-2xl bg-violet-100 flex items-center justify-center mx-auto mb-4">
          <Search class="w-7 h-7 text-violet-600" />
        </div>
        <h3 class="text-lg font-semibold text-gray-900 mb-1">Вы ещё не записаны на курсы</h3>
        <p class="text-gray-500 text-sm mb-5">
          Введите код доступа от преподавателя, чтобы начать обучение.
        </p>
        <NuxtLink
          to="/student/courses"
          class="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-violet-600 text-white text-sm font-medium hover:bg-violet-700 transition"
        >
          Перейти к курсам
        </NuxtLink>
      </div>

      <!-- Course cards -->
      <div v-else class="grid gap-4 sm:grid-cols-2">
        <NuxtLink
          v-for="c in student.courses"
          :key="c.id"
          :to="`/student/courses/${c.id}`"
          class="group bg-white rounded-2xl border border-gray-100 overflow-hidden hover:border-violet-200 hover:shadow-sm transition-all duration-150"
        >
          <div :class="['h-16 bg-gradient-to-br', courseGradient(c.gradient_idx)]" />
          <div class="p-5">
            <div class="font-semibold text-gray-900 group-hover:text-violet-700 transition line-clamp-1">
              {{ c.title }}
            </div>
            <div class="text-sm text-gray-500 mt-1">
              {{ c.completed_lessons }}/{{ c.lessons_count }} уроков
            </div>
            <div class="mt-3 h-1.5 bg-gray-100 rounded-full overflow-hidden">
              <div
                class="h-full bg-violet-500 rounded-full transition-all"
                :style="{ width: `${progressPct(c)}%` }"
              />
            </div>
            <div class="mt-3 flex items-center justify-between text-sm">
              <span class="text-violet-700 font-medium group-hover:text-violet-600">Продолжить</span>
              <ArrowRight class="w-4 h-4 text-violet-700 transform transition group-hover:translate-x-0.5" />
            </div>
          </div>
        </NuxtLink>
      </div>
    </section>

    <!-- ── Статистика ───────────────────────────────────────────── -->
    <section>
      <h2 class="text-base font-semibold text-gray-700 mb-4">Статистика</h2>

      <!-- Dashboard error -->
      <div
        v-if="cabinet.dashboardError"
        class="bg-red-50 border border-red-100 text-red-700 rounded-xl px-4 py-3 text-sm flex items-center justify-between gap-4"
      >
        <span>{{ cabinet.dashboardError }}</span>
        <button
          class="px-3 py-1.5 rounded-lg bg-red-600 text-white text-sm hover:bg-red-700 transition flex-shrink-0"
          @click="cabinet.fetchDashboard()"
        >
          Повторить
        </button>
      </div>

      <!-- Loading skeletons -->
      <div
        v-else-if="cabinet.dashboardLoading && !cabinet.dashboard"
        class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"
      >
        <div
          v-for="n in 4"
          :key="n"
          class="bg-white rounded-2xl border border-gray-100 p-4 h-[88px] animate-pulse"
        >
          <div class="w-9 h-9 rounded-xl bg-gray-100" />
          <div class="h-3 w-20 bg-gray-100 rounded mt-3" />
          <div class="h-4 w-12 bg-gray-100 rounded mt-1.5" />
        </div>
      </div>

      <!-- Loaded -->
      <div
        v-else-if="cabinet.dashboard"
        class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"
      >
        <StudentStatCard
          label="Записан на курсы"
          :value="String(cabinet.dashboard.enrolled_courses)"
          :icon="BookOpen"
          chip="bg-violet-100 text-violet-600"
          to="/student/courses"
        />
        <StudentStatCard
          label="Выполнено заданий"
          :value="String(cabinet.dashboard.completed_assignments)"
          :icon="ClipboardCheck"
          chip="bg-emerald-100 text-emerald-600"
          to="/student/assignments"
        />
        <StudentStatCard
          label="Средний балл"
          :value="avgValue"
          :icon="Award"
          chip="bg-amber-100 text-amber-600"
          to="/student/results"
        />
        <StudentStatCard
          label="Ближайший дедлайн"
          :value="cabinet.dashboard.nearest_deadline?.title ?? '—'"
          :subtitle="cabinet.dashboard.nearest_deadline
            ? formatDate(cabinet.dashboard.nearest_deadline.due_at)
            : 'Нет дедлайнов'"
          :icon="CalendarClock"
          chip="bg-sky-100 text-sky-600"
          to="/student/assignments"
        />
      </div>
    </section>
  </div>
</template>
