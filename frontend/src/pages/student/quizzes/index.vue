<script setup lang="ts">
import { FileQuestion, CheckCircle2, ArrowRight } from 'lucide-vue-next'

definePageMeta({ layout: 'student-cabinet', middleware: ['auth', 'student'] })

const cabinet = useStudentCabinetStore()

onMounted(() => {
  cabinet.fetchQuizzes()
})
</script>

<template>
  <div class="max-w-5xl mx-auto p-6 lg:p-8">
    <h1 class="text-2xl font-semibold text-gray-900 mb-6">Тесты</h1>

    <!-- Error -->
    <div
      v-if="cabinet.quizzesError"
      class="bg-red-50 border border-red-100 text-red-700 rounded-xl px-4 py-3 text-sm flex items-center justify-between gap-4"
    >
      <span>{{ cabinet.quizzesError }}</span>
      <button
        class="px-3 py-1.5 rounded-lg bg-red-600 text-white text-sm hover:bg-red-700 transition flex-shrink-0"
        @click="cabinet.fetchQuizzes()"
      >
        Повторить
      </button>
    </div>

    <!-- Loading -->
    <div v-else-if="cabinet.quizzesLoading" class="space-y-3">
      <div
        v-for="n in 3"
        :key="n"
        class="bg-white rounded-2xl border border-gray-100 p-5 h-20 animate-pulse"
      />
    </div>

    <!-- Empty -->
    <div
      v-else-if="!cabinet.quizzes.length"
      class="bg-white rounded-2xl border border-gray-100 p-8 text-center"
    >
      <div class="w-14 h-14 rounded-2xl bg-violet-100 flex items-center justify-center mx-auto mb-4">
        <FileQuestion class="w-7 h-7 text-violet-600" />
      </div>
      <h2 class="text-lg font-semibold text-gray-900 mb-1">Доступных тестов нет</h2>
      <p class="text-gray-500 text-sm">
        Тесты появятся здесь, когда они станут доступны в ваших курсах.
      </p>
    </div>

    <!-- List -->
    <div v-else class="space-y-3">
      <div
        v-for="q in cabinet.quizzes"
        :key="q.lesson_id"
        class="bg-white rounded-2xl border border-gray-100 p-5 flex items-center gap-4"
      >
        <div class="min-w-0 flex-1">
          <div class="font-medium text-gray-900 line-clamp-1">{{ q.title }}</div>
          <div class="text-sm text-gray-500 mt-0.5 line-clamp-1">{{ q.course_title }}</div>
        </div>

        <div v-if="q.is_passed" class="flex items-center gap-1.5 text-sm text-emerald-600 flex-shrink-0">
          <CheckCircle2 class="w-4 h-4" />
          <span>Пройден{{ q.best_score !== null ? ` · ${q.best_score}%` : '' }}</span>
        </div>

        <NuxtLink
          :to="`/student/courses/${q.course_id}/lessons/${q.lesson_id}`"
          class="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-violet-600 text-white text-sm font-medium hover:bg-violet-700 transition flex-shrink-0"
        >
          {{ q.is_passed ? 'Пересдать' : 'Пройти' }}
          <ArrowRight class="w-4 h-4" />
        </NuxtLink>
      </div>
    </div>
  </div>
</template>
