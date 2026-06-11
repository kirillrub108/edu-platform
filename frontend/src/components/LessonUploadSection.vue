<script setup lang="ts">
import type { CreationModeValue } from '~/composables/useCreationMode'
import { CreationMode } from '~/composables/useCreationMode'

defineProps<{
  pptxPath: string | null
  uploading: boolean
  uploadError: string
  selectedFile: File | null
  mode: CreationModeValue | null
  analyzing: boolean
  analyzeStatus: string
  analyzeMeta: { step?: string; done?: number; total?: number } | null
  analyzeError: string
  generating: boolean
  lessonStatus: string
  showSlideEditor: boolean
  lessonId: string
  cancellingAnalysis: boolean
  creditsSpent: number
  creditsReserved: number
  billedVia: string | null
  needTopup: boolean
}>()

const emit = defineEmits<{
  'file-change': [file: File | null]
  upload: []
  'start-analyze': []
  'cancel-analyze': []
  'toggle-slide-editor': []
  'slide-back': []
  'slide-ready': []
}>()

const innerVisionRef = ref<{
  takeSnapshot(): void
  clearSnapshot(): void
  restoreFromSnapshot(): void
} | null>(null)

defineExpose({
  takeSnapshot: () => innerVisionRef.value?.takeSnapshot(),
  clearSnapshot: () => innerVisionRef.value?.clearSnapshot(),
  restoreFromSnapshot: () => innerVisionRef.value?.restoreFromSnapshot(),
})
</script>

<template>
  <div class="space-y-6">
    <LessonPptxUploader
      :pptx-path="pptxPath"
      :uploading="uploading"
      :error="uploadError"
      :selected-file="selectedFile"
      @file-change="emit('file-change', $event)"
      @upload="emit('upload')"
    />
    <LessonVisionPanel
      v-if="mode === CreationMode.PRESENTATION_AUTO"
      ref="innerVisionRef"
      :has-pptx="!!pptxPath"
      :analyzing="analyzing"
      :analyze-status="analyzeStatus"
      :analyze-step="analyzeMeta?.step ?? ''"
      :progress-done="analyzeMeta?.done ?? 0"
      :progress-total="analyzeMeta?.total ?? 0"
      :analyze-error="analyzeError"
      :generating="generating"
      :lesson-status="lessonStatus"
      :show-slide-editor="showSlideEditor"
      :lesson-id="lessonId"
      :cancelling-analysis="cancellingAnalysis"
      :credits-spent="creditsSpent"
      :credits-reserved="creditsReserved"
      :billed-via="billedVia"
      :need-topup="needTopup"
      @start-analyze="emit('start-analyze')"
      @cancel-analyze="emit('cancel-analyze')"
      @toggle-slide-editor="emit('toggle-slide-editor')"
      @slide-back="emit('slide-back')"
      @slide-ready="emit('slide-ready')"
    />
  </div>
</template>
