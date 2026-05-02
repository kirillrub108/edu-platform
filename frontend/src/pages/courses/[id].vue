<script setup lang="ts">
const route = useRoute()
const { apiFetch } = useApi()

const course = ref<any>(null)
const loading = ref(true)
const newModuleTitle = ref('')

const load = async () => {
  loading.value = true
  try {
    course.value = await apiFetch<any>(`/courses/${route.params.id}`)
  } finally {
    loading.value = false
  }
}

const togglePublish = async () => {
  await apiFetch(`/courses/${route.params.id}/publish`, { method: 'PUT' })
  await load()
}

const addModule = async () => {
  if (!newModuleTitle.value.trim()) return
  await apiFetch(`/courses/${route.params.id}/modules`, {
    method: 'POST',
    body: { title: newModuleTitle.value, order: course.value?.modules?.length ?? 0 },
  })
  newModuleTitle.value = ''
  await load()
}

onMounted(load)
</script>

<template>
  <div v-if="loading" class="text-gray-500">Загрузка…</div>
  <div v-else-if="course">
    <div class="flex items-start justify-between mb-6">
      <div>
        <h1 class="text-2xl font-semibold">{{ course.title }}</h1>
        <p class="text-gray-600">{{ course.description }}</p>
      </div>
      <button class="px-3 py-1 border rounded" @click="togglePublish">
        {{ course.is_published ? 'Снять с публикации' : 'Опубликовать' }}
      </button>
    </div>

    <section>
      <h2 class="text-lg font-semibold mb-3">Модули</h2>
      <div class="space-y-3 mb-4">
        <div v-for="m in course.modules" :key="m.id" class="bg-white border rounded p-3">
          <div class="font-medium">{{ m.title }}</div>
          <ul class="mt-2 text-sm text-gray-700 space-y-1">
            <li v-for="l in m.lessons" :key="l.id" class="flex justify-between">
              <span>{{ l.title }}</span>
              <span class="text-xs text-gray-500">{{ l.status }}</span>
            </li>
            <li v-if="!m.lessons?.length" class="text-gray-400 italic">нет уроков</li>
          </ul>
        </div>
      </div>

      <form class="flex gap-2" @submit.prevent="addModule">
        <input v-model="newModuleTitle" placeholder="Название модуля" class="flex-1 border rounded px-3 py-2" />
        <button class="px-4 py-2 bg-brand text-white rounded">Добавить</button>
      </form>
    </section>
  </div>
</template>
