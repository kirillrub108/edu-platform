<script setup lang="ts">
definePageMeta({ middleware: ['auth'] })

const route = useRoute()
const { apiFetch } = useApi()

// Legacy URL: /student/courses/:id → redirect to first lesson
onMounted(async () => {
  const courseId = route.params.id as string
  try {
    const course = await apiFetch<{ modules: { lessons: { id: string }[] }[] }>(
      `/students/courses/${courseId}`,
    )
    const first = course?.modules?.[0]?.lessons?.[0]
    if (first) {
      await navigateTo(`/student/courses/${courseId}/lessons/${first.id}`, { replace: true })
    } else {
      await navigateTo('/student/dashboard', { replace: true })
    }
  } catch {
    await navigateTo('/student/dashboard', { replace: true })
  }
})
</script>

<template>
  <div class="p-6 text-gray-500 text-sm">Перенаправление…</div>
</template>
