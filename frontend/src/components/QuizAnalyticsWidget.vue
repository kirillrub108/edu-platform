<script setup lang="ts">
import { ArrowRight, BarChart3, Target, TrendingUp } from 'lucide-vue-next'
import type { QuizAnalyticsSummary } from '~/types/analytics'

const { apiFetch } = useApi()

const data = ref<QuizAnalyticsSummary | null>(null)
const loading = ref(true)
const errored = ref(false)

const pct = (v: number | null): string => (v === null ? '—' : `${Math.round(v * 100)}%`)
const fmtDate = (s: string | null): string => {
  if (!s) return '—'
  const d = new Date(s)
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })
}
const studentLabel = (full: string | null, email: string): string => full?.trim() || email

const load = async () => {
  loading.value = true
  errored.value = false
  try {
    data.value = await apiFetch<QuizAnalyticsSummary>('/teacher/analytics/summary')
  } catch (e: any) {
    if (e?.response?.status !== 401) errored.value = true
  } finally {
    loading.value = false
  }
}

onMounted(load)

const hasData = computed(() => !!data.value && data.value.total_attempts > 0)
</script>

<template>
  <div class="cursor-pointer" @click="navigateTo('/analytics/quiz-results')">
  <section class="bg-white border border-gray-100 rounded-2xl p-5 shadow-soft hover:border-violet-200 transition">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-base font-semibold text-gray-900">Тесты студентов</h2>
      <NuxtLink
        to="/analytics/quiz-results"
        class="text-sm text-violet-700 hover:text-violet-800 inline-flex items-center gap-1"
      >
        Все результаты <ArrowRight class="w-3.5 h-3.5" />
      </NuxtLink>
    </div>

    <div v-if="loading" class="space-y-3">
      <div class="h-12 rounded-lg bg-gray-100 animate-pulse" />
      <div class="h-10 rounded-lg bg-gray-100 animate-pulse" />
      <div class="h-10 rounded-lg bg-gray-100 animate-pulse" />
    </div>

    <div v-else-if="errored" class="text-sm text-gray-500">
      Не удалось загрузить аналитику.
    </div>

    <div v-else-if="!hasData" class="text-sm text-gray-500 py-4 text-center">
      Тестов ещё не проходили.
    </div>

    <template v-else-if="data">
      <div class="grid grid-cols-3 gap-3 mb-4">
        <div class="text-center">
          <div class="inline-flex w-8 h-8 rounded-lg bg-violet-100 text-violet-700 items-center justify-center mb-1">
            <BarChart3 class="w-4 h-4" />
          </div>
          <div class="text-lg font-semibold tabular-nums">{{ data.total_attempts }}</div>
          <div class="text-[11px] text-gray-500">попыток</div>
        </div>
        <div class="text-center">
          <div class="inline-flex w-8 h-8 rounded-lg bg-fuchsia-100 text-fuchsia-700 items-center justify-center mb-1">
            <TrendingUp class="w-4 h-4" />
          </div>
          <div class="text-lg font-semibold tabular-nums">{{ pct(data.avg_score) }}</div>
          <div class="text-[11px] text-gray-500">средний</div>
        </div>
        <div class="text-center">
          <div class="inline-flex w-8 h-8 rounded-lg bg-emerald-100 text-emerald-700 items-center justify-center mb-1">
            <Target class="w-4 h-4" />
          </div>
          <div class="text-lg font-semibold tabular-nums">{{ pct(data.pass_rate) }}</div>
          <div class="text-[11px] text-gray-500">сдали</div>
        </div>
      </div>

      <ul class="divide-y divide-gray-50 border-t border-gray-100 pt-2">
        <li
          v-for="(r, idx) in data.recent_submissions.slice(0, 3)"
          :key="`${r.student_id}-${r.lesson_id}-${idx}`"
          class="flex items-center gap-3 py-2 text-sm"
        >
          <div class="flex-1 min-w-0">
            <div class="text-gray-800 truncate">{{ studentLabel(r.student_full_name, r.student_email) }}</div>
            <div class="text-xs text-gray-500 truncate">{{ r.lesson_title }}</div>
          </div>
          <div
            class="text-sm font-medium tabular-nums"
            :class="r.passed ? 'text-emerald-600' : 'text-rose-600'"
          >
            {{ pct(r.score) }}
          </div>
          <div class="text-xs text-gray-500 w-10 text-right">{{ fmtDate(r.completed_at) }}</div>
        </li>
      </ul>
    </template>
  </section>
  </div>
</template>
