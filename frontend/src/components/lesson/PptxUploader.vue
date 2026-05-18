<script setup lang="ts">
import { Upload, CheckCircle2 } from 'lucide-vue-next'

defineProps<{
  pptxPath: string | null
  uploading: boolean
  error: string
  selectedFile: File | null
}>()

const emit = defineEmits<{
  'file-change': [file: File | null]
  upload: []
}>()

const onFileChange = (e: Event) => {
  const input = e.target as HTMLInputElement
  emit('file-change', input.files?.[0] ?? null)
}
</script>

<template>
  <section class="bg-white rounded-2xl border border-gray-100 p-6 shadow-soft">
    <h2 class="text-lg font-semibold text-gray-900 mb-1">Презентация</h2>
    <p class="text-sm text-gray-500 mb-4">Загрузите PPTX, PPT или PDF-файл со слайдами.</p>

    <div
      v-if="pptxPath"
      class="flex items-center gap-2 mb-3 text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-xl px-3 py-2"
    >
      <CheckCircle2 class="w-4 h-4 shrink-0" />
      <span class="truncate">{{ pptxPath.split('/').pop() }}</span>
    </div>

    <div class="flex gap-2 items-center flex-wrap">
      <label class="cursor-pointer inline-flex items-center gap-2 px-4 py-2 border border-gray-200 rounded-xl text-sm font-medium text-gray-700 hover:bg-violet-50 hover:border-violet-200 hover:text-violet-700 transition">
        <Upload class="w-4 h-4" />
        {{ selectedFile ? selectedFile.name : 'Выбрать файл' }}
        <input type="file" accept=".pptx,.ppt,.pdf" class="hidden" @change="onFileChange" />
      </label>
      <UiButton
        v-if="selectedFile"
        variant="primary"
        size="sm"
        :loading="uploading"
        @click="emit('upload')"
      >
        Загрузить
      </UiButton>
    </div>
    <p v-if="error" class="mt-2 text-sm text-rose-600">{{ error }}</p>
  </section>
</template>
