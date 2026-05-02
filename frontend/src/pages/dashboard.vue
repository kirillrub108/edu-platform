<script setup lang="ts">
const { apiFetch } = useApi()
const courses = ref<any[]>([])
const loading = ref(true)

const load = async () => {
  loading.value = true
  try {
    courses.value = await apiFetch<any[]>('/courses/')
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
      <NuxtLink to="/courses/create" class="px-4 py-2 bg-brand text-white rounded">+ Создать курс</NuxtLink>
    </div>

    <p v-if="loading" class="text-gray-500">Загрузка…</p>
    <div v-else-if="!courses.length" class="text-gray-500">У вас пока нет курсов.</div>

    <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <CourseCard v-for="c in courses" :key="c.id" :course="c" />
    </div>
  </div>
</template>
