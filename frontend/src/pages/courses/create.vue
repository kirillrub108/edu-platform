<script setup lang="ts">
const { apiFetch } = useApi()
const config = useRuntimeConfig()

const title = ref('')
const description = ref('')
const pptxFile = ref<File | null>(null)
const uploadInfo = ref<{ file_path: string; file_url: string } | null>(null)
const error = ref<string | null>(null)
const loading = ref(false)

const onFile = (e: Event) => {
  const target = e.target as HTMLInputElement
  pptxFile.value = target.files?.[0] ?? null
}

const submit = async () => {
  error.value = null
  loading.value = true
  try {
    const course = await apiFetch<any>('/courses/', {
      method: 'POST',
      body: { title: title.value, description: description.value || null },
    })

    if (pptxFile.value) {
      const fd = new FormData()
      fd.append('file', pptxFile.value)
      const token = localStorage.getItem('access_token')
      uploadInfo.value = await $fetch<any>(`${config.public.apiBase}/uploads/pptx`, {
        method: 'POST',
        body: fd,
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
    }

    await navigateTo(`/courses/${course.id}`)
  } catch (e: any) {
    error.value = e?.data?.detail ?? 'Failed'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="max-w-xl">
    <h1 class="text-2xl font-semibold mb-6">Новый курс</h1>
    <form class="space-y-4" @submit.prevent="submit">
      <input v-model="title" placeholder="Название курса" required class="w-full border rounded px-3 py-2" />
      <textarea v-model="description" placeholder="Описание" rows="4" class="w-full border rounded px-3 py-2" />
      <div>
        <label class="block text-sm text-gray-600 mb-1">PPTX (опционально)</label>
        <input type="file" accept=".pptx,.ppt,.pdf" @change="onFile" />
      </div>
      <button :disabled="loading" class="px-4 py-2 bg-brand text-white rounded">
        {{ loading ? '...' : 'Создать' }}
      </button>
      <p v-if="error" class="text-sm text-red-600">{{ error }}</p>
    </form>
  </div>
</template>
