<script setup lang="ts">
import { BookOpen, ClipboardCheck, Award, CalendarClock, Search } from 'lucide-vue-next'

definePageMeta({ layout: 'student-cabinet', middleware: ['auth', 'student'] })

const cabinet = useStudentCabinetStore()

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

onMounted(() => {
  cabinet.fetchDashboard()
})
</script>

<template>
  <div class="max-w-5xl mx-auto p-6 lg:p-8">
    <h1 class="text-2xl font-semibold text-gray-900 mb-6">Дашборд</h1>

    <!-- Error -->
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
    <div v-else-if="cabinet.dashboardLoading && !cabinet.dashboard" class="grid gap-4 sm:grid-cols-2">
      <div
        v-for="n in 4"
        :key="n"
        class="bg-white rounded-2xl border border-gray-100 p-5 h-[104px] animate-pulse"
      >
        <div class="w-11 h-11 rounded-xl bg-gray-100" />
        <div class="h-3 w-24 bg-gray-100 rounded mt-3" />
        <div class="h-5 w-16 bg-gray-100 rounded mt-2" />
      </div>
    </div>

    <!-- Loaded -->
    <template v-else-if="cabinet.dashboard">
      <div class="grid gap-4 sm:grid-cols-2">
        <StudentStatCard
          label="Записан на курсы"
          :value="String(cabinet.dashboard.enrolled_courses)"
          :icon="BookOpen"
          chip="bg-violet-100 text-violet-600"
        />
        <StudentStatCard
          label="Выполнено заданий"
          :value="String(cabinet.dashboard.completed_assignments)"
          :icon="ClipboardCheck"
          chip="bg-emerald-100 text-emerald-600"
        />
        <StudentStatCard
          label="Средний балл"
          :value="avgValue"
          :icon="Award"
          chip="bg-amber-100 text-amber-600"
        />
        <StudentStatCard
          label="Ближайший дедлайн"
          :value="cabinet.dashboard.nearest_deadline?.title ?? '—'"
          :subtitle="cabinet.dashboard.nearest_deadline
            ? formatDate(cabinet.dashboard.nearest_deadline.due_at)
            : 'Нет дедлайнов'"
          :icon="CalendarClock"
          chip="bg-sky-100 text-sky-600"
        />
      </div>

      <!-- Empty-state CTA for students with no enrollments -->
      <div
        v-if="cabinet.dashboard.enrolled_courses === 0"
        class="mt-8 bg-white rounded-2xl border border-gray-100 p-8 text-center"
      >
        <div class="w-14 h-14 rounded-2xl bg-violet-100 flex items-center justify-center mx-auto mb-4">
          <Search class="w-7 h-7 text-violet-600" />
        </div>
        <h2 class="text-lg font-semibold text-gray-900 mb-1">Вы ещё не записаны на курсы</h2>
        <p class="text-gray-500 text-sm mb-5">
          Введите код доступа от преподавателя, чтобы начать обучение.
        </p>
        <NuxtLink
          to="/student/courses"
          class="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-violet-600 text-white text-sm font-medium hover:bg-violet-700 transition"
        >
          <Search class="w-4 h-4" />
          Найти курс
        </NuxtLink>
      </div>
    </template>
  </div>
</template>
