<script setup lang="ts">
const route = useRoute()
const { apiFetch } = useApi()

const course = ref<any>(null)
const activeLesson = ref<any>(null)
const loading = ref(true)

const load = async () => {
  loading.value = true
  try {
    course.value = await apiFetch<any>(`/students/courses/${route.params.id}`)
    activeLesson.value = course.value?.modules?.[0]?.lessons?.[0] ?? null
  } finally {
    loading.value = false
  }
}

const markComplete = async () => {
  if (!activeLesson.value) return
  await apiFetch(`/students/lessons/${activeLesson.value.id}/complete`, { method: 'POST' })
}

onMounted(async () => {
  await load()
  await restoreScroll()
})
</script>

<template>
  <div v-if="loading" class="text-gray-500">Загрузка…</div>
  <div v-else-if="course" class="grid grid-cols-1 md:grid-cols-3 gap-6">
    <aside class="md:col-span-1 bg-white border rounded p-3">
      <h2 class="font-semibold mb-2">{{ course.title }}</h2>
      <div v-for="m in course.modules" :key="m.id" class="mb-3">
        <div class="text-sm font-medium text-gray-700">{{ m.title }}</div>
        <ul class="mt-1 text-sm">
          <li
            v-for="l in m.lessons"
            :key="l.id"
            class="cursor-pointer px-2 py-1 rounded hover:bg-gray-100"
            :class="{ 'bg-gray-100 font-medium': activeLesson?.id === l.id }"
            @click="activeLesson = l"
          >
            {{ l.title }}
          </li>
        </ul>
      </div>
    </aside>

    <section class="md:col-span-2 space-y-3">
      <LessonPlayer v-if="activeLesson" :lesson="activeLesson" />
      <button v-if="activeLesson" class="px-3 py-1 bg-brand text-white rounded text-sm" @click="markComplete">
        Отметить пройденным
      </button>
    </section>
  </div>
</template>
