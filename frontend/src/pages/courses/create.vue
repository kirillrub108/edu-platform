<script setup lang="ts">
definePageMeta({ middleware: ['auth', 'teacher'] })

const { apiFetch } = useApi()
const title = ref('')
const description = ref('')
const error = ref<string | null>(null)
const loading = ref(false)

const submit = async () => {
  error.value = null
  loading.value = true
  try {
    const course = await apiFetch<any>('/courses/', {
      method: 'POST',
      body: { title: title.value, description: description.value || null },
    })
    await navigateTo(`/courses/${course.id}`)
  } catch (e: any) {
    error.value = e?.data?.detail ?? 'Ошибка при создании курса'
  } finally {
    loading.value = false
  }
}

onMounted(restoreScroll)
</script>

<template>
  <div class="max-w-xl">
    <NuxtLink to="/dashboard" class="text-sm text-brand hover:underline block mb-4">← Назад</NuxtLink>
    <h1 class="text-2xl font-semibold mb-6">Новый курс</h1>

    <form class="space-y-4 bg-white border rounded-xl p-6" @submit.prevent="submit">
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">Название</label>
        <input
          v-model="title"
          placeholder="Введите название курса"
          required
          class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
        />
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">Описание</label>
        <textarea
          v-model="description"
          placeholder="Краткое описание курса"
          rows="4"
          class="w-full border rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-brand/30"
        />
      </div>

      <p v-if="error" class="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">
        {{ error }}
      </p>

      <button
        type="submit"
        :disabled="loading"
        class="px-5 py-2 bg-brand text-white rounded-lg font-medium disabled:opacity-50 transition"
      >
        {{ loading ? 'Создание…' : 'Создать курс' }}
      </button>
    </form>
  </div>
</template>
