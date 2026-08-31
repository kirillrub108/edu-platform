<script setup lang="ts">
definePageMeta({ middleware: ['auth'] })

const route = useRoute()
const { apiFetch } = useApi()

const empty = ref(false)
const courseTitle = ref('')

// Legacy URL: /student/courses/:id → redirect to first lesson.
// /students/courses/{id} already prunes to the student-visible module/lesson
// tree (visibility_service.visible_module_tree) — an empty `modules` here
// means the course is legitimately empty for this student, not a 403/404.
onMounted(async () => {
  const courseId = route.params.id as string
  try {
    const course = await apiFetch<{ title: string; modules: { lessons: { id: string }[] }[] }>(
      `/students/courses/${courseId}`,
    )
    // flatMap across all modules, not just the first — a module with no
    // visible lessons must not hide lessons in the next one.
    const first = course?.modules?.flatMap((m) => m.lessons)[0]
    if (first) {
      await navigateTo(`/student/courses/${courseId}/lessons/${first.id}`, { replace: true })
    } else {
      courseTitle.value = course?.title ?? ''
      empty.value = true
    }
  } catch {
    await navigateTo('/student/dashboard', { replace: true })
  }
})
</script>

<template>
  <div v-if="empty" class="p-6 max-w-lg mx-auto">
    <NuxtLink to="/student/dashboard" class="text-sm text-brand hover:underline mb-4 block">← Мои курсы</NuxtLink>
    <h1 v-if="courseTitle" class="text-xl font-semibold text-gray-900 mb-3">{{ courseTitle }}</h1>
    <p class="text-sm text-gray-500 bg-gray-50 border border-gray-200 rounded-lg px-4 py-3">
      Курс временно пуст — преподаватель ещё готовит материалы.
    </p>
  </div>
  <div v-else class="p-6 text-gray-500 text-sm">Перенаправление…</div>
</template>
