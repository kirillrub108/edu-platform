<script setup lang="ts">
defineProps<{
  voices: Array<{ value: string; label: string }>
  selectedVoice: string
  generating: boolean
  cancellingVideo: boolean
  lessonStatus: string
  showPipeline: boolean
  pipelineStages: Array<{ label: string; pct?: number }>
  currentStageIdx: number
  taskError: string
  canGenerateVideo: boolean
  videoUrl: string | null
  analyzing: boolean
  hasPptx: boolean
  isAuto: boolean
  isManual: boolean
  scriptIsEmpty: boolean
  creditsSpent: number
  creditsReserved: number
  billedVia: string | null
  needTopup: boolean
  cancelled: boolean
  latestPublished: boolean
  publishing: boolean
}>()

const emit = defineEmits<{
  'update:selectedVoice': [voice: string]
  generate: []
  cancel: []
  publish: []
  viewHistory: []
  'video-url-expired': []
}>()
</script>

<template>
  <LessonVideoGenerationPanel
    :voices="voices"
    :selected-voice="selectedVoice"
    :generating="generating"
    :cancelling-video="cancellingVideo"
    :lesson-status="lessonStatus"
    :show-pipeline="showPipeline"
    :pipeline-stages="pipelineStages"
    :current-stage-idx="currentStageIdx"
    :task-error="taskError"
    :can-generate-video="canGenerateVideo"
    :video-url="videoUrl"
    :analyzing="analyzing"
    :has-pptx="hasPptx"
    :is-auto="isAuto"
    :is-manual="isManual"
    :script-is-empty="scriptIsEmpty"
    :credits-spent="creditsSpent"
    :credits-reserved="creditsReserved"
    :billed-via="billedVia"
    :need-topup="needTopup"
    :cancelled="cancelled"
    :latest-published="latestPublished"
    :publishing="publishing"
    @update:selected-voice="emit('update:selectedVoice', $event)"
    @generate="emit('generate')"
    @cancel="emit('cancel')"
    @publish="emit('publish')"
    @view-history="emit('viewHistory')"
    @video-url-expired="emit('video-url-expired')"
  />
</template>
