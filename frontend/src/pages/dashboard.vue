<script setup lang="ts">
import { Plus, BookOpen, CheckCircle2, Layers, AlertCircle } from 'lucide-vue-next'

definePageMeta({ middleware: ['auth', 'teacher'], layout: 'bare' })

const { apiFetch } = useApi()
const courses = ref<any[]>([])
const loading = ref(true)
const apiError = ref('')

const load = async () => {
  loading.value = true
  apiError.value = ''
  try {
    courses.value = await apiFetch<any[]>('/courses/')
  } catch (e: any) {
    if (e?.response?.status !== 401) {
      apiError.value = 'Не удалось загрузить курсы. Проверьте, что бэкенд запущен.'
    }
  } finally {
    loading.value = false
  }
}

const stats = computed(() => ({
  total: courses.value.length,
  published: courses.value.filter(c => c.is_published).length,
  lessons: courses.value.reduce((a, c) => a + (c.lessons_count ?? 0), 0),
}))

onMounted(async () => {
  await load()
  await restoreScroll()
})
</script>

<template>
  <div class="flex">
    <AppSidebar />
    <main class="flex-1 px-6 lg:px-10 py-8">
      <div class="flex items-center justify-between mb-6 gap-4 flex-wrap">
        <div>
          <div class="text-xs text-gray-500 mb-1 uppercase tracking-wide">Преподаватель</div>
          <h1 class="text-2xl font-semibold text-gray-900">Мои курсы</h1>
        </div>
        <NuxtLink to="/courses/create">
          <UiButton variant="primary">
            <template #icon><Plus class="w-4 h-4" /></template>
            Создать курс
          </UiButton>
        </NuxtLink>
      </div>

      <!-- stats bar -->
      <div class="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-8">
        <div class="bg-white border border-gray-100 rounded-2xl p-4 flex items-center gap-3 shadow-soft">
          <div class="w-10 h-10 rounded-xl bg-violet-100 text-violet-700 grid place-items-center">
            <BookOpen class="w-5 h-5" />
          </div>
          <div>
            <div class="text-2xl font-semibold leading-none">{{ stats.total }}</div>
            <div class="text-xs text-gray-500 mt-1">всего курсов</div>
          </div>
        </div>
        <div class="bg-white border border-gray-100 rounded-2xl p-4 flex items-center gap-3 shadow-soft">
          <div class="w-10 h-10 rounded-xl bg-emerald-100 text-emerald-700 grid place-items-center">
            <CheckCircle2 class="w-5 h-5" />
          </div>
          <div>
            <div class="text-2xl font-semibold leading-none">{{ stats.published }}</div>
            <div class="text-xs text-gray-500 mt-1">опубликовано</div>
          </div>
        </div>
        <div class="bg-white border border-gray-100 rounded-2xl p-4 flex items-center gap-3 shadow-soft">
          <div class="w-10 h-10 rounded-xl bg-fuchsia-100 text-fuchsia-700 grid place-items-center">
            <Layers class="w-5 h-5" />
          </div>
          <div>
            <div class="text-2xl font-semibold leading-none">{{ stats.lessons }}</div>
            <div class="text-xs text-gray-500 mt-1">уроков всего</div>
          </div>
        </div>
      </div>

      <!-- error state -->
      <div
        v-if="apiError"
        class="flex items-start gap-3 text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-2xl p-4"
      >
        <AlertCircle class="w-5 h-5 shrink-0 mt-0.5" />
        <div>{{ apiError }}</div>
      </div>

      <!-- loading -->
      <div v-else-if="loading" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <SkeletonCard v-for="i in 6" :key="i" />
      </div>

      <!-- empty -->
      <div
        v-else-if="!courses.length"
        class="text-center py-20 bg-white rounded-2xl border border-gray-100"
      >
        <div class="w-16 h-16 rounded-2xl bg-violet-100 text-violet-700 grid place-items-center mx-auto mb-4">
          <BookOpen class="w-8 h-8" />
        </div>
        <h2 class="text-lg font-semibold text-gray-900">Нет курсов пока</h2>
        <p class="text-sm text-gray-500 mt-1 mb-5">Создайте первый и загрузите слайды лекции.</p>
        <NuxtLink to="/courses/create">
          <UiButton variant="primary">
            <template #icon><Plus class="w-4 h-4" /></template>
            Создать курс
          </UiButton>
        </NuxtLink>
      </div>

      <!-- grid -->
      <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <CourseCard
          v-for="(c, i) in courses"
          :key="c.id"
          :course="{ ...c, gradient_idx: i }"
        />
      </div>
    </main>
  </div>
</template>
