<script setup lang="ts">
defineProps<{
  voices: Array<{ value: string; label: string }>
  selectedVoice: string
  selectedSpeed: number
  selectedPitch: number
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
  sampleLoading: boolean
  sampleError: string
}>()

const emit = defineEmits<{
  'update:selectedVoice': [voice: string]
  'update:selectedSpeed': [speed: number]
  'update:selectedPitch': [pitch: number]
  generate: []
  cancel: []
  publish: []
  viewHistory: []
  'video-url-expired': []
  'play-sample': []
}>()
</script>

<template>
  <LessonVideoGenerationPanel
    :voices="voices"
    :selected-voice="selectedVoice"
    :selected-speed="selectedSpeed"
    :selected-pitch="selectedPitch"
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
    :sample-loading="sampleLoading"
    :sample-error="sampleError"
    @update:selected-voice="emit('update:selectedVoice', $event)"
    @update:selected-speed="emit('update:selectedSpeed', $event)"
    @update:selected-pitch="emit('update:selectedPitch', $event)"
    @generate="emit('generate')"
    @cancel="emit('cancel')"
    @publish="emit('publish')"
    @view-history="emit('viewHistory')"
    @video-url-expired="emit('video-url-expired')"
    @play-sample="emit('play-sample')"
  />
</template>
