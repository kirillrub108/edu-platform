<script setup lang="ts">
import { BookOpen } from 'lucide-vue-next'

definePageMeta({ layout: 'student-cabinet', middleware: ['auth', 'student'] })

// Reuses the existing student store (/students/my-courses + enroll) rather than
// duplicating that logic. Loading/error are handled here since that store has
// no error state of its own.
const studentStore = useStudentStore()

const loading = ref(true)
const error = ref<string | null>(null)

const enrollCode = ref('')
const enrolling = ref(false)
const enrollError = ref<string | null>(null)

const load = async () => {
  loading.value = true
  error.value = null
  try {
    await studentStore.fetchCourses()
  } catch {
    error.value = 'Не удалось загрузить курсы. Попробуйте ещё раз.'
  } finally {
    loading.value = false
  }
}

const handleEnroll = async () => {
  const code = enrollCode.value.trim()
  if (!code || enrolling.value) return
  enrolling.value = true
  enrollError.value = null
  try {
    await studentStore.enroll(code)
    enrollCode.value = ''
  } catch {
    enrollError.value = 'Курс не найден или код недействителен.'
  } finally {
    enrolling.value = false
  }
}

const progress = (completed: number, total: number) =>
  total > 0 ? Math.round((completed / total) * 100) : 0

onMounted(load)
</script>

<template>
  <div class="max-w-5xl mx-auto p-6 lg:p-8">
    <h1 class="text-2xl font-semibold text-gray-900 mb-6">Мои курсы</h1>

    <!-- Enroll by access code -->
    <form class="mb-6 flex gap-2 max-w-md" @submit.prevent="handleEnroll">
      <input
        v-model="enrollCode"
        placeholder="Код доступа от преподавателя"
        class="flex-1 min-w-0 border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-violet-400"
      />
      <button
        type="submit"
        :disabled="enrolling"
        class="px-4 py-2 bg-violet-600 text-white rounded-lg text-sm hover:bg-violet-700 transition whitespace-nowrap disabled:opacity-50"
      >
        Записаться
      </button>
    </form>
    <p v-if="enrollError" class="-mt-4 mb-6 text-sm text-red-600">{{ enrollError }}</p>

    <!-- Error -->
    <div
      v-if="error"
      class="bg-red-50 border border-red-100 text-red-700 rounded-xl px-4 py-3 text-sm flex items-center justify-between gap-4"
    >
      <span>{{ error }}</span>
      <button
        class="px-3 py-1.5 rounded-lg bg-red-600 text-white text-sm hover:bg-red-700 transition flex-shrink-0"
        @click="load"
      >
        Повторить
      </button>
    </div>

    <!-- Loading -->
    <div v-else-if="loading" class="grid gap-4 sm:grid-cols-2">
      <div
        v-for="n in 4"
        :key="n"
        class="bg-white rounded-2xl border border-gray-100 p-5 h-28 animate-pulse"
      >
        <div class="h-4 w-2/3 bg-gray-100 rounded" />
        <div class="h-3 w-1/3 bg-gray-100 rounded mt-3" />
        <div class="h-1.5 w-full bg-gray-100 rounded-full mt-4" />
      </div>
    </div>

    <!-- Empty -->
    <div
      v-else-if="!studentStore.courses.length"
      class="bg-white rounded-2xl border border-gray-100 p-8 text-center"
    >
      <div class="w-14 h-14 rounded-2xl bg-violet-100 flex items-center justify-center mx-auto mb-4">
        <BookOpen class="w-7 h-7 text-violet-600" />
      </div>
      <h2 class="text-lg font-semibold text-gray-900 mb-1">Пока нет курсов</h2>
      <p class="text-gray-500 text-sm">
        Введите код доступа выше, чтобы записаться на свой первый курс.
      </p>
    </div>

    <!-- List -->
    <div v-else class="grid gap-4 sm:grid-cols-2">
      <NuxtLink
        v-for="c in studentStore.courses"
        :key="c.id"
        :to="`/student/courses/${c.id}`"
        class="bg-white rounded-2xl border border-gray-100 p-5 hover:border-violet-200 hover:shadow-sm transition group"
      >
        <div class="font-medium text-gray-900 group-hover:text-violet-700 transition line-clamp-1">
          {{ c.title }}
        </div>
        <div class="text-sm text-gray-500 mt-1">
          {{ c.completed_lessons }}/{{ c.lessons_count }} уроков
        </div>
        <div class="mt-3 h-1.5 bg-gray-100 rounded-full overflow-hidden">
          <div
            class="h-full bg-violet-500 rounded-full transition-all"
            :style="{ width: `${progress(c.completed_lessons, c.lessons_count)}%` }"
          />
        </div>
      </NuxtLink>
    </div>
  </div>
</template>
