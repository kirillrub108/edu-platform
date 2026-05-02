<script setup lang="ts">
defineProps<{
  lesson: {
    id: string
    title: string
    content_type: 'video' | 'text' | 'quiz'
    video_url?: string | null
    text_content?: string | null
    status: string
  }
}>()
</script>

<template>
  <div class="bg-white rounded-lg border border-gray-200 p-4">
    <h2 class="font-semibold text-lg mb-3">{{ lesson.title }}</h2>

    <div v-if="lesson.content_type === 'video'">
      <div v-if="lesson.video_url">
        <video :src="lesson.video_url" controls class="w-full rounded" />
      </div>
      <div v-else class="text-sm text-gray-500">
        Video status: {{ lesson.status }}
      </div>
    </div>

    <div v-else-if="lesson.content_type === 'text'" class="prose max-w-none">
      <p>{{ lesson.text_content }}</p>
    </div>

    <div v-else class="text-sm text-gray-600">
      Quiz content not implemented in player yet.
    </div>
  </div>
</template>
