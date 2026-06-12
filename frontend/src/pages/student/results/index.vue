<script setup lang="ts">
import { BarChart3 } from 'lucide-vue-next'
import type { StudentResult } from '~/stores/studentCabinet'

definePageMeta({ layout: 'student-cabinet', middleware: ['auth', 'student'] })

const cabinet = useStudentCabinetStore()

const dateFmt = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
})
const formatDate = (iso: string) => dateFmt.format(new Date(iso))

const statusBadge = (r: StudentResult): { label: string; cls: string } => {
  if (r.passed === true) return { label: 'Сдан', cls: 'bg-emerald-50 text-emerald-700' }
  if (r.passed === false) return { label: 'Не сдан', cls: 'bg-red-50 text-red-700' }
  return { label: 'На проверке', cls: 'bg-amber-50 text-amber-700' }
}

onMounted(() => {
  cabinet.fetchResults()
})
</script>

<template>
  <div class="max-w-5xl mx-auto p-6 lg:p-8">
    <h1 class="text-2xl font-semibold text-gray-900 mb-6">Результаты</h1>

    <!-- Error -->
    <div
      v-if="cabinet.resultsError"
      class="bg-red-50 border border-red-100 text-red-700 rounded-xl px-4 py-3 text-sm flex items-center justify-between gap-4"
    >
      <span>{{ cabinet.resultsError }}</span>
      <button
        class="px-3 py-1.5 rounded-lg bg-red-600 text-white text-sm hover:bg-red-700 transition flex-shrink-0"
        @click="cabinet.fetchResults()"
      >
        Повторить
      </button>
    </div>

    <!-- Loading -->
    <div v-else-if="cabinet.resultsLoading" class="bg-white rounded-2xl border border-gray-100 p-5 space-y-3">
      <div v-for="n in 5" :key="n" class="h-8 bg-gray-100 rounded animate-pulse" />
    </div>

    <!-- Empty -->
    <div
      v-else-if="!cabinet.results.length"
      class="bg-white rounded-2xl border border-gray-100 p-8 text-center"
    >
      <div class="w-14 h-14 rounded-2xl bg-violet-100 flex items-center justify-center mx-auto mb-4">
        <BarChart3 class="w-7 h-7 text-violet-600" />
      </div>
      <h2 class="text-lg font-semibold text-gray-900 mb-1">Результатов пока нет</h2>
      <p class="text-gray-500 text-sm">
        Здесь появятся ваши баллы после прохождения тестов.
      </p>
    </div>

    <!-- Table -->
    <div v-else class="bg-white rounded-2xl border border-gray-100 overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-left text-gray-500 border-b border-gray-100">
              <th class="px-5 py-3 font-medium">Тест</th>
              <th class="px-5 py-3 font-medium">Дата</th>
              <th class="px-5 py-3 font-medium">Балл</th>
              <th class="px-5 py-3 font-medium">Статус</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="r in cabinet.results"
              :key="r.attempt_id"
              class="border-b border-gray-50 last:border-0"
            >
              <td class="px-5 py-3">
                <div class="font-medium text-gray-900 line-clamp-1">{{ r.title }}</div>
                <div class="text-xs text-gray-400 line-clamp-1">{{ r.course_title }}</div>
              </td>
              <td class="px-5 py-3 text-gray-600 whitespace-nowrap">{{ formatDate(r.date) }}</td>
              <td class="px-5 py-3 text-gray-900 font-medium whitespace-nowrap">
                {{ r.score !== null ? `${r.score}%` : '—' }}
              </td>
              <td class="px-5 py-3">
                <span
                  class="inline-flex px-2.5 py-1 rounded-full text-xs font-medium"
                  :class="statusBadge(r).cls"
                >
                  {{ statusBadge(r).label }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
