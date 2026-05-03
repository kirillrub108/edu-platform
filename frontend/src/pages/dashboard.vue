<script setup lang="ts">
definePageMeta({ middleware: ['auth', 'teacher'] })

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
      apiError.value = 'Не удалось загрузить курсы. Проверьте что бэкенд запущен.'
    }
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-2xl font-semibold">Мои курсы</h1>
      <NuxtLink to="/courses/create" class="px-4 py-2 bg-brand text-white rounded-lg text-sm font-medium">
        + Создать курс
      </NuxtLink>
    </div>

    <p v-if="loading" class="text-gray-500">Загрузка…</p>

    <div v-else-if="apiError" class="text-red-600 bg-red-50 border border-red-200 rounded-lg p-4 text-sm">
      {{ apiError }}
    </div>

    <div v-else-if="!courses.length" class="text-center py-16 text-gray-400">
      <p class="text-lg mb-3">У вас пока нет курсов</p>
      <NuxtLink to="/courses/create" class="px-4 py-2 bg-brand text-white rounded-lg text-sm">
        Создать первый курс
      </NuxtLink>
    </div>

    <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <CourseCard v-for="c in courses" :key="c.id" :course="c" />
    </div>
  </div>
</template>
