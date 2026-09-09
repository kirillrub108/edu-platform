<script setup lang="ts">
import { ChevronLeft } from 'lucide-vue-next'

/**
 * Teacher's course-wide knowledge base. One request instead of N per-lesson
 * calls; the tree itself (and every edit path) lives in KnowledgeCourseTree.
 */
definePageMeta({ middleware: ['auth', 'teacher'], layout: 'workspace' })

const route = useRoute()

const courseId = computed(() => {
  const id = route.params.id
  return Array.isArray(id) ? id[0]! : (id as string)
})
</script>

<template>
  <div class="space-y-6">
    <NuxtLink
      :to="`/courses/${courseId}`"
      class="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800 transition"
    >
      <ChevronLeft class="w-4 h-4" />
      К курсу
    </NuxtLink>

    <h1 class="text-2xl font-semibold text-gray-900">База знаний курса</h1>

    <KnowledgeCourseTree :course-id="courseId" />
  </div>
</template>
