<script setup lang="ts">
import { ClipboardList, ArrowRight } from 'lucide-vue-next'
import type { StudentAssignment } from '~/stores/studentCabinet'

definePageMeta({ layout: 'student-cabinet', middleware: ['auth', 'student'] })

const cabinet = useStudentCabinetStore()

const dateFmt = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
})
const formatDue = (iso: string | null) => (iso ? dateFmt.format(new Date(iso)) : 'Без срока')

const statusBadge = (a: StudentAssignment): { label: string; cls: string } => {
  switch (a.submission_status) {
    case 'returned':
      return { label: 'Оценено', cls: 'bg-emerald-50 text-emerald-700' }
    case 'submitted':
    case 'graded':
      return { label: 'На проверке', cls: 'bg-amber-50 text-amber-700' }
    case 'draft':
      return { label: 'Черновик', cls: 'bg-gray-100 text-gray-600' }
    default:
      return { label: 'Не начато', cls: 'bg-gray-100 text-gray-600' }
  }
}

onMounted(() => {
  cabinet.fetchAssignments()
})
</script>

<template>
  <div class="max-w-5xl mx-auto p-6 lg:p-8">
    <h1 class="text-2xl font-semibold text-gray-900 mb-6">Задания</h1>

    <!-- Error -->
    <div
      v-if="cabinet.assignmentsError"
      class="bg-red-50 border border-red-100 text-red-700 rounded-xl px-4 py-3 text-sm flex items-center justify-between gap-4"
    >
      <span>{{ cabinet.assignmentsError }}</span>
      <button
        class="px-3 py-1.5 rounded-lg bg-red-600 text-white text-sm hover:bg-red-700 transition flex-shrink-0"
        @click="cabinet.fetchAssignments()"
      >
        Повторить
      </button>
    </div>

    <!-- Loading -->
    <div v-else-if="cabinet.assignmentsLoading" class="space-y-3">
      <div
        v-for="n in 3"
        :key="n"
        class="bg-white rounded-2xl border border-gray-100 p-5 h-24 animate-pulse"
      />
    </div>

    <!-- Empty -->
    <div
      v-else-if="!cabinet.assignments.length"
      class="bg-white rounded-2xl border border-gray-100 p-8 text-center"
    >
      <div class="w-14 h-14 rounded-2xl bg-violet-100 flex items-center justify-center mx-auto mb-4">
        <ClipboardList class="w-7 h-7 text-violet-600" />
      </div>
      <h2 class="text-lg font-semibold text-gray-900 mb-1">Заданий пока нет</h2>
      <p class="text-gray-500 text-sm">
        Задания из ваших курсов появятся здесь.
      </p>
    </div>

    <!-- List -->
    <div v-else class="space-y-3">
      <div
        v-for="a in cabinet.assignments"
        :key="a.assignment_id"
        class="bg-white rounded-2xl border border-gray-100 p-5 flex items-center gap-4"
      >
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="font-medium text-gray-900 line-clamp-1">{{ a.title }}</span>
            <span
              class="inline-flex px-2.5 py-0.5 rounded-full text-xs font-medium"
              :class="statusBadge(a).cls"
            >
              {{ statusBadge(a).label }}
            </span>
          </div>
          <div class="text-sm text-gray-500 mt-0.5 line-clamp-1">{{ a.course_title }}</div>
          <div class="text-xs text-gray-400 mt-1">
            Срок: {{ formatDue(a.due_at) }}
            <template v-if="a.score !== null"> · Балл: {{ a.score }}%</template>
          </div>
        </div>

        <NuxtLink
          :to="`/student/courses/${a.course_id}/lessons/${a.lesson_id}`"
          class="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-violet-600 text-white text-sm font-medium hover:bg-violet-700 transition flex-shrink-0"
        >
          Открыть
          <ArrowRight class="w-4 h-4" />
        </NuxtLink>
      </div>
    </div>
  </div>
</template>
