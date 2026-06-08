<script setup lang="ts">
import { Film, Upload, AlertCircle } from 'lucide-vue-next'

const props = defineProps<{
  videoUrl: string | null
  selectedFile: File | null
  uploading: boolean
  uploadError: string
}>()

const emit = defineEmits<{
  'file-change': [file: File | null]
  upload: []
}>()

const ACCEPT = '.mp4,.webm,.mov,.mkv,video/mp4,video/webm,video/quicktime,video/x-matroska'

const onInput = (e: Event) => {
  const target = e.target as HTMLInputElement
  emit('file-change', target.files?.[0] ?? null)
}
</script>

<template>
  <section class="bg-white rounded-2xl border border-gray-100 p-6 shadow-soft space-y-4">
    <div class="flex items-center gap-2">
      <Film class="w-5 h-5 text-violet-600" />
      <h2 class="text-lg font-semibold text-gray-900">Готовое видео</h2>
    </div>
    <p class="text-sm text-gray-500">
      Загрузите готовый видеофайл — урок сразу опубликуется. Поддерживаются MP4, WebM, MOV, MKV (до 2 ГБ).
    </p>

    <div class="flex flex-wrap items-center gap-3">
      <label
        class="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl border border-violet-200 text-violet-700 hover:bg-violet-50 cursor-pointer text-sm font-medium transition"
      >
        <Upload class="w-4 h-4" />
        Выбрать файл
        <input type="file" :accept="ACCEPT" class="hidden" @change="onInput" >
      </label>
      <span v-if="props.selectedFile" class="text-sm text-gray-600 truncate max-w-xs">
        {{ props.selectedFile.name }}
      </span>

      <UiButton
        :loading="props.uploading"
        :disabled="!props.selectedFile"
        @click="emit('upload')"
      >
        Загрузить
      </UiButton>
    </div>

    <div
      v-if="props.uploadError"
      class="flex items-start gap-2 text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-xl p-3"
    >
      <AlertCircle class="w-4 h-4 shrink-0 mt-0.5" />
      <span>{{ props.uploadError }}</span>
    </div>

    <video
      v-if="props.videoUrl"
      :key="props.videoUrl"
      :src="props.videoUrl"
      controls
      class="w-full rounded-xl bg-black"
    />
  </section>
</template>
