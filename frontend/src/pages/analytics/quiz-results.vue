<script setup lang="ts">
import {
  AlertCircle,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  BarChart3,
  ChevronLeft,
  ChevronRight,
  ChevronRight as ChevronRightIcon,
  Inbox,
  RefreshCw,
  Search,
  Target,
  TrendingUp,
  Users,
} from 'lucide-vue-next'
import type {
  CourseOption,
  QuizAnalyticsSummary,
  QuizLessonSort,
  QuizLessonStatsPage,
  SortOrder,
} from '~/types/analytics'

definePageMeta({ middleware: ['auth', 'teacher'], layout: 'bare' })

const { apiFetch } = useApi()

const summary = ref<QuizAnalyticsSummary | null>(null)
const page = ref<QuizLessonStatsPage | null>(null)
const courses = ref<CourseOption[]>([])

const courseId = ref<string>('')
const search = ref('')
const sort = ref<QuizLessonSort>('last_attempt_at')
const order = ref<SortOrder>('desc')
const pageNum = ref(1)
const pageSize = 20

const loadingSummary = ref(true)
const loadingPage = ref(true)
const errSummary = ref('')
const errPage = ref('')

const pct = (v: number | null): string => (v === null ? '—' : `${Math.round(v * 100)}%`)
const fmtDate = (s: string | null): string => {
  if (!s) return '—'
  const d = new Date(s)
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' })
}
const studentLabel = (full: string | null, email: string): string => full?.trim() || email

const loadSummary = async () => {
  loadingSummary.value = true
  errSummary.value = ''
  try {
    summary.value = await apiFetch<QuizAnalyticsSummary>('/teacher/analytics/summary')
  } catch (e: any) {
    if (e?.response?.status !== 401) {
      errSummary.value = 'Не удалось загрузить сводку.'
    }
  } finally {
    loadingSummary.value = false
  }
}

const loadCourses = async () => {
  try {
    const list = await apiFetch<Array<{ id: string; title: string }>>('/courses/')
    courses.value = list.map(c => ({ id: c.id, title: c.title }))
  } catch {
    /* falls back to empty selector — non-blocking */
  }
}

const loadPage = async () => {
  loadingPage.value = true
  errPage.value = ''
  try {
    const qs = new URLSearchParams()
    if (courseId.value) qs.set('course_id', courseId.value)
    if (search.value.trim()) qs.set('search', search.value.trim())
    qs.set('sort', sort.value)
    qs.set('order', order.value)
    qs.set('page', String(pageNum.value))
    qs.set('page_size', String(pageSize))
    page.value = await apiFetch<QuizLessonStatsPage>(
      `/teacher/analytics/quiz-lessons?${qs.toString()}`,
    )
  } catch (e: any) {
    if (e?.response?.status !== 401) {
      errPage.value = 'Не удалось загрузить уроки.'
    }
  } finally {
    loadingPage.value = false
  }
}

let searchTimer: ReturnType<typeof setTimeout> | null = null
watch(search, () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    pageNum.value = 1
    loadPage()
  }, 300)
})

watch(courseId, () => {
  pageNum.value = 1
  loadPage()
})

const setSort = (col: QuizLessonSort) => {
  if (sort.value === col) {
    order.value = order.value === 'desc' ? 'asc' : 'desc'
  } else {
    sort.value = col
    order.value = col === 'lesson_title' ? 'asc' : 'desc'
  }
  pageNum.value = 1
  loadPage()
}

const sortIconFor = (col: QuizLessonSort) => {
  if (sort.value !== col) return ArrowUpDown
  return order.value === 'desc' ? ArrowDown : ArrowUp
}

const totalPages = computed(() => {
  if (!page.value) return 1
  return Math.max(1, Math.ceil(page.value.total / pageSize))
})

const refresh = async () => {
  await Promise.all([loadSummary(), loadPage()])
}

const openLesson = (lessonId: string) => {
  navigateTo(`/lessons/${lessonId}/quiz-results`)
}

onMounted(async () => {
  await Promise.all([loadSummary(), loadCourses(), loadPage()])
})
</script>

<template>
  <div class="flex">
    <AppSidebar />
    <main class="flex-1 px-6 lg:px-10 py-8">
      <div class="flex items-center justify-between mb-6 gap-4 flex-wrap">
        <div>
          <div class="text-xs text-gray-500 mb-1 uppercase tracking-wide">Аналитика</div>
          <h1 class="text-2xl font-semibold text-gray-900">Результаты тестов</h1>
        </div>
        <UiButton variant="secondary" :loading="loadingSummary || loadingPage" @click="refresh">
          <template #icon><RefreshCw class="w-4 h-4" /></template>
          Обновить
        </UiButton>
      </div>

      <!-- KPI cards -->
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
        <div class="bg-white border border-gray-100 rounded-2xl p-4 flex items-center gap-3 shadow-soft">
          <div class="w-10 h-10 rounded-xl bg-violet-100 text-violet-700 grid place-items-center">
            <BarChart3 class="w-5 h-5" />
          </div>
          <div>
            <div class="text-2xl font-semibold leading-none tabular-nums">
              {{ summary?.total_quiz_lessons ?? '—' }}
            </div>
            <div class="text-xs text-gray-500 mt-1">тестов в курсах</div>
          </div>
        </div>
        <div class="bg-white border border-gray-100 rounded-2xl p-4 flex items-center gap-3 shadow-soft">
          <div class="w-10 h-10 rounded-xl bg-indigo-100 text-indigo-700 grid place-items-center">
            <Users class="w-5 h-5" />
          </div>
          <div>
            <div class="text-2xl font-semibold leading-none tabular-nums">
              {{ summary?.total_attempts ?? '—' }}
            </div>
            <div class="text-xs text-gray-500 mt-1">всего попыток</div>
          </div>
        </div>
        <div class="bg-white border border-gray-100 rounded-2xl p-4 flex items-center gap-3 shadow-soft">
          <div class="w-10 h-10 rounded-xl bg-fuchsia-100 text-fuchsia-700 grid place-items-center">
            <TrendingUp class="w-5 h-5" />
          </div>
          <div>
            <div class="text-2xl font-semibold leading-none tabular-nums">
              {{ pct(summary?.avg_score ?? null) }}
            </div>
            <div class="text-xs text-gray-500 mt-1">средний балл</div>
          </div>
        </div>
        <div class="bg-white border border-gray-100 rounded-2xl p-4 flex items-center gap-3 shadow-soft">
          <div class="w-10 h-10 rounded-xl bg-emerald-100 text-emerald-700 grid place-items-center">
            <Target class="w-5 h-5" />
          </div>
          <div>
            <div class="text-2xl font-semibold leading-none tabular-nums">
              {{ pct(summary?.pass_rate ?? null) }}
            </div>
            <div class="text-xs text-gray-500 mt-1">сдали тест</div>
          </div>
        </div>
      </div>

      <div
        v-if="errSummary"
        class="flex items-start gap-3 text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-2xl p-4 mb-6"
      >
        <AlertCircle class="w-5 h-5 shrink-0 mt-0.5" />
        <div>{{ errSummary }}</div>
      </div>

      <!-- Recent submissions -->
      <section
        v-if="summary && summary.recent_submissions.length > 0"
        class="bg-white border border-gray-100 rounded-2xl p-5 shadow-soft mb-6"
      >
        <h2 class="text-base font-semibold text-gray-900 mb-3">Последние результаты</h2>
        <ul class="divide-y divide-gray-50">
          <li
            v-for="(r, idx) in summary.recent_submissions.slice(0, 5)"
            :key="`${r.student_id}-${r.lesson_id}-${idx}`"
            class="flex items-center gap-3 py-2.5 text-sm cursor-pointer hover:bg-violet-50/40 -mx-2 px-2 rounded-lg transition"
            @click="openLesson(r.lesson_id)"
          >
            <div class="flex-1 min-w-0">
              <div class="text-gray-800 truncate">{{ studentLabel(r.student_full_name, r.student_email) }}</div>
              <div class="text-xs text-gray-500 truncate">
                {{ r.lesson_title }} · {{ r.course_title }}
              </div>
            </div>
            <div
              class="text-sm font-medium tabular-nums"
              :class="r.passed ? 'text-emerald-600' : 'text-rose-600'"
            >
              {{ pct(r.score) }}
            </div>
            <div class="text-xs text-gray-400 w-20 text-right">{{ fmtDate(r.completed_at) }}</div>
          </li>
        </ul>
      </section>

      <!-- Filters -->
      <section class="bg-white border border-gray-100 rounded-2xl p-4 shadow-soft mb-3">
        <div class="flex flex-wrap items-center gap-3">
          <div class="relative flex-1 min-w-[200px]">
            <Search class="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              v-model="search"
              type="text"
              placeholder="Поиск по названию урока"
              class="w-full pl-9 pr-3 py-2 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-300"
            >
          </div>
          <select
            v-model="courseId"
            class="border border-gray-200 rounded-xl px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-300"
          >
            <option value="">Все курсы</option>
            <option v-for="c in courses" :key="c.id" :value="c.id">{{ c.title }}</option>
          </select>
        </div>
      </section>

      <!-- Lessons table -->
      <section class="bg-white border border-gray-100 rounded-2xl shadow-soft overflow-hidden">
        <div
          v-if="errPage"
          class="flex items-start gap-3 text-sm text-rose-700 bg-rose-50 border-b border-rose-200 p-4"
        >
          <AlertCircle class="w-5 h-5 shrink-0 mt-0.5" />
          <div>{{ errPage }}</div>
        </div>

        <div v-if="loadingPage" class="p-6 space-y-3">
          <div v-for="i in 5" :key="i" class="h-12 rounded-lg bg-gray-100 animate-pulse" />
        </div>

        <div
          v-else-if="page && page.total === 0"
          class="px-6 py-16 text-center text-gray-500"
        >
          <Inbox class="w-10 h-10 mx-auto mb-3 text-gray-300" />
          <p class="text-sm">Студенты ещё не проходили тесты</p>
        </div>

        <table v-else-if="page" class="w-full text-sm">
          <thead class="bg-gray-50 text-gray-500">
            <tr>
              <th
                class="px-4 py-3 text-left font-medium cursor-pointer select-none"
                @click="setSort('lesson_title')"
              >
                <span class="inline-flex items-center gap-1">
                  Урок
                  <component :is="sortIconFor('lesson_title')" class="w-3.5 h-3.5" />
                </span>
              </th>
              <th
                class="px-4 py-3 text-center font-medium cursor-pointer select-none"
                @click="setSort('attempts_count')"
              >
                <span class="inline-flex items-center gap-1">
                  Попыток
                  <component :is="sortIconFor('attempts_count')" class="w-3.5 h-3.5" />
                </span>
              </th>
              <th class="px-4 py-3 text-center font-medium">Студентов</th>
              <th
                class="px-4 py-3 text-center font-medium cursor-pointer select-none"
                @click="setSort('avg_score')"
              >
                <span class="inline-flex items-center gap-1">
                  Средний балл
                  <component :is="sortIconFor('avg_score')" class="w-3.5 h-3.5" />
                </span>
              </th>
              <th
                class="px-4 py-3 text-center font-medium cursor-pointer select-none"
                @click="setSort('pass_rate')"
              >
                <span class="inline-flex items-center gap-1">
                  % сдавших
                  <component :is="sortIconFor('pass_rate')" class="w-3.5 h-3.5" />
                </span>
              </th>
              <th
                class="px-4 py-3 text-left font-medium cursor-pointer select-none"
                @click="setSort('last_attempt_at')"
              >
                <span class="inline-flex items-center gap-1">
                  Последняя попытка
                  <component :is="sortIconFor('last_attempt_at')" class="w-3.5 h-3.5" />
                </span>
              </th>
              <th class="px-4 py-3 w-12" />
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-50">
            <tr
              v-for="row in page.items"
              :key="row.lesson_id"
              class="hover:bg-violet-50/40 cursor-pointer transition"
              @click="openLesson(row.lesson_id)"
            >
              <td class="px-4 py-3">
                <div class="text-gray-900 font-medium">{{ row.lesson_title }}</div>
                <div class="text-xs text-gray-500">
                  {{ row.course_title }} · {{ row.module_title }}
                </div>
              </td>
              <td class="px-4 py-3 text-center tabular-nums text-gray-700">
                {{ row.attempts_count }}
              </td>
              <td class="px-4 py-3 text-center tabular-nums text-gray-700">
                {{ row.students_count }}
              </td>
              <td class="px-4 py-3 text-center tabular-nums text-gray-700">
                {{ pct(row.avg_score) }}
              </td>
              <td class="px-4 py-3 text-center tabular-nums">
                <span
                  v-if="row.pass_rate !== null"
                  :class="row.pass_rate >= 0.6 ? 'text-emerald-600' : 'text-rose-600'"
                >{{ pct(row.pass_rate) }}</span>
                <span v-else class="text-gray-400">—</span>
              </td>
              <td class="px-4 py-3 text-gray-500 tabular-nums">
                {{ fmtDate(row.last_attempt_at) }}
              </td>
              <td class="px-4 py-3 text-gray-400">
                <ChevronRightIcon class="w-4 h-4" />
              </td>
            </tr>
          </tbody>
        </table>

        <!-- Pagination -->
        <div
          v-if="page && page.total > pageSize"
          class="flex items-center justify-between px-4 py-3 border-t border-gray-100 text-sm"
        >
          <div class="text-gray-500">
            Страница {{ page.page }} из {{ totalPages }} · всего {{ page.total }}
          </div>
          <div class="flex items-center gap-2">
            <button
              :disabled="pageNum <= 1"
              class="px-3 py-1.5 rounded-lg border border-gray-200 text-gray-700 hover:bg-gray-50 disabled:opacity-40 disabled:pointer-events-none inline-flex items-center gap-1"
              @click="pageNum--; loadPage()"
            >
              <ChevronLeft class="w-4 h-4" /> Назад
            </button>
            <button
              :disabled="pageNum >= totalPages"
              class="px-3 py-1.5 rounded-lg border border-gray-200 text-gray-700 hover:bg-gray-50 disabled:opacity-40 disabled:pointer-events-none inline-flex items-center gap-1"
              @click="pageNum++; loadPage()"
            >
              Далее <ChevronRight class="w-4 h-4" />
            </button>
          </div>
        </div>
      </section>
    </main>
  </div>
</template>
