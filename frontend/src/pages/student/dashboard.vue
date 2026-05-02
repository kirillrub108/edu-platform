<script setup lang="ts">
const { apiFetch } = useApi()
const courses = ref<any[]>([])
const loading = ref(true)
const code = ref('')

const load = async () => {
  loading.value = true
  try {
    courses.value = await apiFetch<any[]>('/students/my-courses')
  } finally {
    loading.value = false
  }
}

const enroll = async () => {
  if (!code.value.trim()) return
  await apiFetch('/students/enroll', {
    method: 'POST',
    body: { access_code: code.value },
  })
  code.value = ''
  await load()
}

onMounted(load)
</script>

<template>
  <div>
    <h1 class="text-2xl font-semibold mb-6">Мои курсы</h1>

    <form class="flex gap-2 mb-6 max-w-md" @submit.prevent="enroll">
      <input v-model="code" placeholder="Код доступа" class="flex-1 border rounded px-3 py-2" />
      <button class="px-4 py-2 bg-brand text-white rounded">Записаться</button>
    </form>

    <p v-if="loading" class="text-gray-500">Загрузка…</p>
    <p v-else-if="!courses.length" class="text-gray-500">Вы пока не записаны ни на один курс.</p>
    <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <CourseCard v-for="c in courses" :key="c.id" :course="c" :to="`/student/courses/${c.id}`" />
    </div>
  </div>
</template>
