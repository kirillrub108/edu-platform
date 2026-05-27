<script setup lang="ts">
import { BookOpen } from 'lucide-vue-next'

definePageMeta({ layout: 'student', middleware: ['auth'] })

const studentStore = useStudentStore()
</script>

<template>
  <div class="h-full flex items-center justify-center p-6 text-center">
    <div v-if="studentStore.courses.length">
      <h1 class="text-2xl font-semibold text-gray-800 mb-2">Добро пожаловать!</h1>
      <p class="text-gray-500">Выберите курс из списка слева, чтобы начать обучение.</p>
    </div>
    <div v-else class="max-w-xs">
      <div class="w-16 h-16 rounded-2xl bg-violet-100 flex items-center justify-center mx-auto mb-6">
        <BookOpen class="w-8 h-8 text-violet-600" />
      </div>
      <h1 class="text-xl font-semibold text-gray-900 mb-2">Начните обучение</h1>
      <p class="text-gray-500 text-sm">
        Введите код доступа от преподавателя в поле слева, чтобы записаться на курс.
      </p>
    </div>
  </div>
</template>
