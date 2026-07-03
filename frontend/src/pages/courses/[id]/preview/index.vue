<script setup lang="ts">
definePageMeta({ layout: 'student', middleware: ['auth', 'teacher'] })

const route = useRoute()
const previewStore = usePreviewStore()

const courseId = computed(() => route.params.id as string)
const empty = ref(false)
const error = ref('')

// ?module_id= autofocuses that module (entry-point capture lives in the layout).
onMounted(async () => {
  try {
    await previewStore.fetchCourse(courseId.value)
  } catch (e: any) {
    error.value = e?.response?.status === 404 ? 'Курс не найден.' : 'Не удалось загрузить курс.'
    return
  }

  const modules = previewStore.course?.modules ?? []
  const moduleId = route.query.module_id
  const focused =
    typeof moduleId === 'string' ? modules.find((m) => m.id === moduleId) : undefined
  const target =
    focused?.lessons[0] ?? modules.flatMap((m) => m.lessons)[0]

  if (target) {
    await navigateTo(`/courses/${courseId.value}/preview/lessons/${target.id}`, {
      replace: true,
    })
  } else {
    empty.value = true
  }
})
</script>

<template>
  <div class="p-6 text-sm text-gray-500">
    <template v-if="error">{{ error }}</template>
    <template v-else-if="empty">
      В курсе пока нет уроков — добавьте модуль и урок, чтобы посмотреть его глазами студента.
    </template>
    <template v-else>Загрузка предпросмотра…</template>
  </div>
</template>
