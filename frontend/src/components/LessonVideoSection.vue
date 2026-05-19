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
}>()

const emit = defineEmits<{
  'update:selectedVoice': [voice: string]
  generate: []
  cancel: []
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
    @update:selected-voice="emit('update:selectedVoice', $event)"
    @generate="emit('generate')"
    @cancel="emit('cancel')"
  />
</template>
