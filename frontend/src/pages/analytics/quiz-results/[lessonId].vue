<script setup lang="ts">
import {
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  Inbox,
} from 'lucide-vue-next'
import type {
  QuizLessonStats,
  QuizLessonStatsPage,
  QuizSubmissionPage,
} from '~/types/analytics'

definePageMeta({ middleware: ['auth', 'teacher'], layout: 'bare' })

const route = useRoute()
const { apiFetch } = useApi()

const lessonId = computed(() => {
  const id = route.params.lessonId
  return Array.isArray(id) ? id[0] : (id as string)
})

const lessonStats = ref<QuizLessonStats | null>(null)
const submissions = ref<QuizSubmissionPage | null>(null)
const loading = ref(true)
const errMsg = ref('')
const notFound = ref(false)

const pageNum = ref(1)
const pageSize = 20

const pct = (v: number | null): string => (v === null ? '—' : `${Math.round(v * 100)}%`)
const fmtDate = (s: string | null): string => {
  if (!s) return '—'
  const d = new Date(s)
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' })
}
const studentLabel = (full: string | null, email: string): string => full?.trim() || email

// Fetch the row from the paginated lessons endpoint (filtered by lesson_title)
// to avoid spinning up a dedicated single-lesson endpoint. Falls back to
// querying without filters if the title match is ambiguous.
const loadLessonStats = async () => {
  const qs = new URLSearchParams({ page: '1', page_size: '100' })
  const data = await apiFetch<QuizLessonStatsPage>(
    `/teacher/analytics/quiz-lessons?${qs.toString()}`,
  )
  const match = data.items.find(it => it.lesson_id === lessonId.value)
  if (match) lessonStats.value = match
}

const loadSubmissions = async () => {
  loading.value = true
  errMsg.value = ''
  notFound.value = false
  try {
    const qs = new URLSearchParams({
      page: String(pageNum.value),
      page_size: String(pageSize),
    })
    submissions.value = await apiFetch<QuizSubmissionPage>(
      `/teacher/analytics/quiz-lessons/${lessonId.value}/submissions?${qs.toString()}`,
    )
  } catch (e: any) {
    if (e?.response?.status === 404) {
      notFound.value = true
    } else if (e?.response?.status !== 401) {
      errMsg.value = 'Не удалось загрузить результаты.'
    }
  } finally {
    loading.value = false
  }
}

const totalPages = computed(() => {
  if (!submissions.value) return 1
  return Math.max(1, Math.ceil(submissions.value.total / pageSize))
})

onMounted(async () => {
  await Promise.all([loadLessonStats(), loadSubmissions()])
})
</script>

<template>
  <div class="flex">
    <AppSidebar />
    <main class="flex-1 px-6 lg:px-10 py-8">
      <!-- Breadcrumb -->
      <nav class="text-sm text-gray-500 mb-4 flex items-center gap-2">
        <NuxtLink to="/analytics/quiz-results" class="hover:text-violet-700 transition">
          Результаты тестов
        </NuxtLink>
        <span class="text-gray-300">/</span>
        <span class="text-gray-800 truncate">
          {{ lessonStats?.lesson_title ?? 'Урок' }}
        </span>
      </nav>

      <div v-if="notFound" class="bg-white rounded-2xl border border-gray-100 p-10 text-center">
        <AlertCircle class="w-10 h-10 mx-auto text-rose-400 mb-3" />
        <div class="text-gray-700">Урок не найден или вам недоступен.</div>
        <NuxtLink to="/analytics/quiz-results" class="inline-block mt-4 text-sm text-violet-700 hover:underline">
          ← К списку тестов
        </NuxtLink>
      </div>

      <template v-else>
        <!-- Aggregate row -->
        <section
          v-if="lessonStats"
          class="bg-white border border-gray-100 rounded-2xl p-5 shadow-soft mb-6"
        >
          <div class="flex items-start justify-between gap-4 flex-wrap">
            <div class="min-w-0">
              <h1 class="text-xl font-semibold text-gray-900 truncate">
                {{ lessonStats.lesson_title }}
              </h1>
              <div class="text-sm text-gray-500 mt-1">
                {{ lessonStats.course_title }} · {{ lessonStats.module_title }}
              </div>
            </div>
            <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div>
                <div class="text-xs text-gray-500">Попыток</div>
                <div class="text-lg font-semibold tabular-nums">{{ lessonStats.attempts_count }}</div>
              </div>
              <div>
                <div class="text-xs text-gray-500">Студентов</div>
                <div class="text-lg font-semibold tabular-nums">{{ lessonStats.students_count }}</div>
              </div>
              <div>
                <div class="text-xs text-gray-500">Средний балл</div>
                <div class="text-lg font-semibold tabular-nums">{{ pct(lessonStats.avg_score) }}</div>
              </div>
              <div>
                <div class="text-xs text-gray-500">% сдавших</div>
                <div
                  class="text-lg font-semibold tabular-nums"
                  :class="(lessonStats.pass_rate ?? 0) >= 0.6 ? 'text-emerald-600' : 'text-rose-600'"
                >
                  {{ pct(lessonStats.pass_rate) }}
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- Submissions table -->
        <section class="bg-white border border-gray-100 rounded-2xl shadow-soft overflow-hidden">
          <div
            v-if="errMsg"
            class="flex items-start gap-3 text-sm text-rose-700 bg-rose-50 border-b border-rose-200 p-4"
          >
            <AlertCircle class="w-5 h-5 shrink-0 mt-0.5" />
            <div>{{ errMsg }}</div>
          </div>

          <div v-if="loading" class="p-6 space-y-3">
            <div v-for="i in 6" :key="i" class="h-12 rounded-lg bg-gray-100 animate-pulse" />
          </div>

          <div
            v-else-if="submissions && submissions.total === 0"
            class="px-6 py-16 text-center text-gray-500"
          >
            <Inbox class="w-10 h-10 mx-auto mb-3 text-gray-300" />
            <p class="text-sm">Никто ещё не сдавал этот тест.</p>
          </div>

          <table v-else-if="submissions" class="w-full text-sm">
            <thead class="bg-gray-50 text-gray-500">
              <tr>
                <th class="px-4 py-3 text-left font-medium">Студент</th>
                <th class="px-4 py-3 text-left font-medium">Email</th>
                <th class="px-4 py-3 text-center font-medium">Балл</th>
                <th class="px-4 py-3 text-center font-medium">Статус</th>
                <th class="px-4 py-3 text-left font-medium">Дата</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-50">
              <tr v-for="s in submissions.items" :key="`${s.student_id}-${s.lesson_id}`">
                <td class="px-4 py-3 text-gray-900">{{ studentLabel(s.student_full_name, s.student_email) }}</td>
                <td class="px-4 py-3 text-gray-500">{{ s.student_email }}</td>
                <td class="px-4 py-3 text-center tabular-nums">
                  <span
                    class="font-medium"
                    :class="s.passed ? 'text-emerald-600' : 'text-rose-600'"
                  >{{ pct(s.score) }}</span>
                </td>
                <td class="px-4 py-3 text-center">
                  <span
                    v-if="s.passed"
                    class="text-xs bg-emerald-100 text-emerald-700 px-2 py-0.5 rounded-full"
                  >пройден</span>
                  <span
                    v-else
                    class="text-xs bg-rose-100 text-rose-700 px-2 py-0.5 rounded-full"
                  >не сдан</span>
                </td>
                <td class="px-4 py-3 text-gray-500 tabular-nums">{{ fmtDate(s.completed_at) }}</td>
              </tr>
            </tbody>
          </table>

          <div
            v-if="submissions && submissions.total > pageSize"
            class="flex items-center justify-between px-4 py-3 border-t border-gray-100 text-sm"
          >
            <div class="text-gray-500">
              Страница {{ submissions.page }} из {{ totalPages }} · всего {{ submissions.total }}
            </div>
            <div class="flex items-center gap-2">
              <button
                :disabled="pageNum <= 1"
                class="px-3 py-1.5 rounded-lg border border-gray-200 text-gray-700 hover:bg-gray-50 disabled:opacity-40 disabled:pointer-events-none inline-flex items-center gap-1"
                @click="pageNum--; loadSubmissions()"
              >
                <ChevronLeft class="w-4 h-4" /> Назад
              </button>
              <button
                :disabled="pageNum >= totalPages"
                class="px-3 py-1.5 rounded-lg border border-gray-200 text-gray-700 hover:bg-gray-50 disabled:opacity-40 disabled:pointer-events-none inline-flex items-center gap-1"
                @click="pageNum++; loadSubmissions()"
              >
                Далее <ChevronRight class="w-4 h-4" />
              </button>
            </div>
          </div>
        </section>
      </template>
    </main>
  </div>
</template>
