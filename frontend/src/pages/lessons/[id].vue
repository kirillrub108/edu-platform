<script setup lang="ts">
import { AlertCircle } from 'lucide-vue-next'

definePageMeta({ middleware: ['auth', 'teacher'] })

const route = useRoute()
const lessonId = computed(() => {
  const id = route.params.id
  return Array.isArray(id) ? id[0] : id
})

const showSlideEditor = ref(false)
const warningDismissed = ref(false)
const visionPanelRef = ref<{
  takeSnapshot(): void
  clearSnapshot(): void
  restoreFromSnapshot(): void
} | null>(null)

const {
  lesson, loading, error, mode, script, scriptSaveStatus,
  pptxFile, uploading, uploadError, scriptFile, uploadingScript, scriptUploadError,
  isAuto, isManual, load, onModeSelect, uploadPptx, uploadScriptFile, flushScript,
} = useLessonData(lessonId)

const {
  startAnalysis, cancelAnalysis, analyzing, analyzeMeta, analyzeStatus, analyzeError,
  cancellingAnalysis, stopPolling: stopVisionPolling,
} = useVisionAnalysis(lessonId, lesson, visionPanelRef, showSlideEditor)

const {
  generateVideo: _generateVideo, cancelVideo, generating, taskError,
  selectedVoice, voices, canGenerateVideo, showPipeline,
  pipelineStages, currentStageIdx, cancellingVideo, stopPolling: stopVideoPolling,
} = useVideoGeneration(lessonId, lesson, mode, script, flushScript, isAuto, showSlideEditor)

// Reset the LLM-fallback warning banner each time generation starts.
const generateVideo = async () => { warningDismissed.value = false; await _generateVideo() }

const lessonStatusForBadge = computed(() => {
  if (analyzing.value) return 'analyzing'
  if (generating.value) return 'processing'
  const s = lesson.value?.status
  return ['draft', 'analyzing', 'ready_for_edit', 'processing', 'published', 'error'].includes(s) ? s : 'draft'
})

onMounted(async () => { await load(); await restoreScroll() })

onUnmounted(() => { stopVisionPolling(); stopVideoPolling() })

// Stop stale polling when navigating between lessons within the same route pattern.
watch(lessonId, (newId, oldId) => {
  if (newId === oldId) return
  stopVisionPolling()
  stopVideoPolling()
  showSlideEditor.value = false
  warningDismissed.value = false
  void load()
})
</script>

<template>
  <div v-if="loading" class="text-gray-500">Загрузка…</div>

  <div
    v-else-if="error"
    class="flex items-start gap-3 text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-2xl p-4"
  >
    <AlertCircle class="w-5 h-5 shrink-0 mt-0.5" />
    <div>{{ error }}</div>
  </div>

  <div v-else-if="lesson" class="space-y-6 max-w-4xl">
    <LessonHeader :title="lesson.title" :status="lessonStatusForBadge" />

    <div
      v-if="lesson.last_warning && !warningDismissed"
      class="flex items-start gap-3 text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-2xl p-4"
    >
      <AlertCircle class="w-5 h-5 shrink-0 mt-0.5 text-amber-500" />
      <span class="flex-1">{{ lesson.last_warning }}</span>
      <button
        type="button"
        class="shrink-0 text-amber-500 hover:text-amber-700 transition leading-none"
        aria-label="Закрыть"
        @click="warningDismissed = true"
      >✕</button>
    </div>

    <section class="bg-white rounded-2xl border border-gray-100 p-6 shadow-soft">
      <CreationModeChooser :model-value="mode" @update:model-value="onModeSelect" />
    </section>

    <LessonUploadSection
      v-if="isManual || isAuto"
      ref="visionPanelRef"
      :pptx-path="lesson.pptx_path ?? null"
      :uploading="uploading"
      :upload-error="uploadError"
      :selected-file="pptxFile"
      :mode="mode"
      :analyzing="analyzing"
      :analyze-status="analyzeStatus"
      :analyze-meta="analyzeMeta"
      :analyze-error="analyzeError"
      :generating="generating"
      :lesson-status="lesson.status"
      :show-slide-editor="showSlideEditor"
      :lesson-id="lessonId"
      :cancelling-analysis="cancellingAnalysis"
      @file-change="pptxFile = $event; uploadError = ''"
      @upload="uploadPptx"
      @start-analyze="startAnalysis"
      @cancel-analyze="cancelAnalysis"
      @toggle-slide-editor="showSlideEditor = !showSlideEditor"
      @slide-back="showSlideEditor = false"
      @slide-ready="async () => { showSlideEditor = false; await generateVideo() }"
    />

    <LessonScriptSection
      v-if="isManual"
      v-model="script"
      :save-status="scriptSaveStatus"
      :script-file="scriptFile"
      :uploading-script="uploadingScript"
      :script-upload-error="scriptUploadError"
      @script-file-change="scriptFile = $event; scriptUploadError = ''"
      @upload-script="uploadScriptFile"
    />

    <LessonVideoSection
      v-if="isManual || isAuto"
      v-model:selected-voice="selectedVoice"
      :voices="voices"
      :generating="generating"
      :cancelling-video="cancellingVideo"
      :lesson-status="lesson.status"
      :show-pipeline="showPipeline"
      :pipeline-stages="pipelineStages"
      :current-stage-idx="currentStageIdx"
      :task-error="taskError"
      :can-generate-video="canGenerateVideo"
      :video-url="lesson.video_url ?? null"
      :analyzing="analyzing"
      :has-pptx="!!lesson.pptx_path"
      :is-auto="isAuto"
      :is-manual="isManual"
      :script-is-empty="!script.trim()"
      @generate="generateVideo"
      @cancel="cancelVideo"
    />
  </div>
</template>
