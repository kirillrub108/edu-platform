<script setup lang="ts">
defineProps<{
  course: {
    id: string
    title: string
    description?: string | null
    is_published: boolean
    lessons_count?: number
  }
  to?: string
}>()
</script>

<template>
  <NuxtLink
    :to="to ?? `/courses/${course.id}`"
    class="block bg-white rounded-lg border border-gray-200 p-4 hover:border-brand transition"
  >
    <div class="flex items-start justify-between">
      <h3 class="font-semibold">{{ course.title }}</h3>
      <span
        class="text-xs px-2 py-0.5 rounded"
        :class="course.is_published ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'"
      >
        {{ course.is_published ? 'published' : 'draft' }}
      </span>
    </div>
    <p v-if="course.description" class="text-sm text-gray-600 mt-2 line-clamp-2">
      {{ course.description }}
    </p>
  </NuxtLink>
</template>
