<script setup lang="ts">
const props = defineProps<{
  lesson: {
    id: string
    title: string
    content_type: 'video' | 'text' | 'quiz'
    video_url?: string | null
    text_content?: string | null
    status: string
  }
}>()

const emit = defineEmits<{ 'video-url-expired': [] }>()

// One retry per URL: once emitted, suppress further error events until the
// parent provides a new URL (which resets this guard via the watch below).
const retried = ref(false)

watch(
  () => props.lesson.video_url,
  () => { retried.value = false },
)

const onVideoError = () => {
  if (!retried.value) {
    retried.value = true
    emit('video-url-expired')
  }
}
</script>

<template>
  <div
    v-if="lesson.content_type === 'video'"
    class="bg-black rounded-2xl overflow-hidden aspect-video relative"
  >
    <video
      v-if="lesson.video_url"
      :key="lesson.video_url"
      :src="lesson.video_url"
      controls
      class="w-full h-full object-contain"
      @error="onVideoError"
    />
    <div
      v-else
      class="absolute inset-0 grid place-items-center text-sm text-gray-300"
    >
      Видео: {{ lesson.status }}
    </div>
  </div>

  <div
    v-else-if="lesson.content_type === 'text'"
    class="bg-white border border-gray-100 rounded-2xl p-6 prose max-w-none"
  >
    <p>{{ lesson.text_content }}</p>
  </div>

  <div
    v-else-if="lesson.content_type === 'quiz'"
    class="bg-white border border-gray-100 rounded-2xl p-6 text-sm text-gray-600"
  >
    Отметьте урок пройденным, чтобы открыть тест.
  </div>
</template>
