<script setup lang="ts">
import { Plus, BookOpen, AlertCircle, Search } from 'lucide-vue-next'

definePageMeta({ middleware: ['auth', 'teacher'], layout: 'bare' })

const { apiFetch } = useApi()
const courses = ref<any[]>([])
const loading = ref(true)
const apiError = ref('')
const search = ref('')

const load = async () => {
  loading.value = true
  apiError.value = ''
  try {
    courses.value = await apiFetch<any[]>('/courses/')
  } catch (e: any) {
    if (e?.response?.status !== 401) {
      apiError.value = 'Не удалось загрузить курсы.'
    }
  } finally {
    loading.value = false
  }
}

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return courses.value
  return courses.value.filter(c =>
    (c.title ?? '').toLowerCase().includes(q)
    || (c.description ?? '').toLowerCase().includes(q),
  )
})

onMounted(load)
</script>

<template>
  <div class="flex">
    <AppSidebar />
    <main class="flex-1 px-6 lg:px-10 py-8">
      <div class="flex items-center justify-between mb-6 gap-4 flex-wrap">
        <div>
          <div class="text-xs text-gray-500 mb-1 uppercase tracking-wide">Преподаватель</div>
          <h1 class="text-2xl font-semibold text-gray-900">Все курсы</h1>
        </div>
        <NuxtLink to="/courses/create">
          <UiButton variant="primary">
            <template #icon><Plus class="w-4 h-4" /></template>
            Создать курс
          </UiButton>
        </NuxtLink>
      </div>

      <div class="bg-white border border-gray-100 rounded-2xl p-3 shadow-soft mb-4">
        <div class="relative">
          <Search class="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            v-model="search"
            type="text"
            placeholder="Поиск по названию или описанию"
            class="w-full pl-9 pr-3 py-2 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-300"
          >
        </div>
      </div>

      <div
        v-if="apiError"
        class="flex items-start gap-3 text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-2xl p-4 mb-6"
      >
        <AlertCircle class="w-5 h-5 shrink-0 mt-0.5" />
        <div>{{ apiError }}</div>
      </div>

      <div v-if="loading" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <SkeletonCard v-for="i in 6" :key="i" />
      </div>

      <div
        v-else-if="!filtered.length"
        class="text-center py-20 bg-white rounded-2xl border border-gray-100"
      >
        <div class="w-16 h-16 rounded-2xl bg-violet-100 text-violet-700 grid place-items-center mx-auto mb-4">
          <BookOpen class="w-8 h-8" />
        </div>
        <h2 class="text-lg font-semibold text-gray-900">
          {{ search ? 'Ничего не найдено' : 'Нет курсов пока' }}
        </h2>
        <p v-if="!search" class="text-sm text-gray-500 mt-1 mb-5">
          Создайте первый и загрузите слайды лекции.
        </p>
      </div>

      <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <CourseCard
          v-for="(c, i) in filtered"
          :key="c.id"
          :course="{ ...c, gradient_idx: i }"
        />
      </div>
    </main>
  </div>
</template>
