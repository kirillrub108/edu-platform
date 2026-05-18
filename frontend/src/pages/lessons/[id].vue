<script setup lang="ts">
import { AlertCircle } from 'lucide-vue-next'
import { CreationMode, type CreationModeValue } from '~/composables/useCreationMode'

definePageMeta({ middleware: ['auth', 'teacher'] })

const route = useRoute()
const { apiFetch } = useApi()

const lesson = ref<any>(null)
const loading = ref(true)
const error = ref('')

const mode = ref<CreationModeValue | null>(null)

const pptxFile = ref<File | null>(null)
const uploading = ref(false)
const uploadError = ref('')

const script = ref('')
const savingScript = ref(false)

const scriptFile = ref<File | null>(null)
const uploadingScript = ref(false)
const scriptUploadError = ref('')

const voices = [
  { value: 'xenia',   label: 'Ксения (жен.)' },
  { value: 'baya',    label: 'Байя (жен.)' },
  { value: 'kseniya', label: 'Ксения-2 (жен.)' },
  { value: 'aidar',   label: 'Айдар (муж.)' },
  { value: 'eugene',  label: 'Евгений (муж.)' },
]
const selectedVoice = ref<string>('xenia')

const analyzeTaskId = ref<string | null>(null)
const analyzeStatus = ref<string>('')
const analyzeMeta = ref<{ step?: string; done?: number; total?: number } | null>(null)
const analyzeError = ref('')
const analyzing = ref(false)
let analyzeTimer: ReturnType<typeof setInterval> | null = null

const showSlideEditor = ref(false)
const showScriptEditor = ref(true)

const taskId = ref<string | null>(null)
const taskStatus = ref<string>('')
const taskMeta = ref<{ step: string; done: number; total: number } | null>(null)
const taskError = ref('')
const generating = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

let statusPollTimer: ReturnType<typeof setInterval> | null = null

const stopStatusPolling = () => {
  if (statusPollTimer) {
    clearInterval(statusPollTimer)
    statusPollTimer = null
  }
}

const pollForAnalysisCompletion = async () => {
  try {
    const data = await apiFetch<any>(`/lessons/${route.params.id}`)
    if (data.status !== 'analyzing') {
      stopStatusPolling()
      analyzing.value = false
      lesson.value = data
      script.value = data.script ?? data.text_content ?? ''
      if (data.status === 'ready_for_edit') {
        showSlideEditor.value = true
      } else if (data.status === 'error') {
        analyzeError.value = 'Ошибка анализа. Попробуйте запустить снова.'
      }
    }
  } catch {
    // network glitch — keep polling
  }
}

const pollForVideoCompletion = async () => {
  try {
    const data = await apiFetch<any>(`/lessons/${route.params.id}`)
    if (data.status !== 'processing') {
      stopStatusPolling()
      generating.value = false
      lesson.value = data
      script.value = data.script ?? data.text_content ?? ''
      if (data.status === 'error') {
        taskError.value = 'Ошибка генерации видео.'
      }
    }
  } catch {
    // network glitch — keep polling
  }
}

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    lesson.value = await apiFetch<any>(`/lessons/${route.params.id}`)
    script.value = lesson.value.script ?? lesson.value.text_content ?? ''
    if (lesson.value.creation_mode) {
      mode.value = lesson.value.creation_mode as CreationModeValue
    }
    if (lesson.value.status === 'analyzing') {
      mode.value = CreationMode.PRESENTATION_AUTO
      if (!analyzing.value) {
        analyzing.value = true
        stopAnalyzePolling()
        stopStatusPolling()
        if (lesson.value.analyze_task_id) {
          analyzeTaskId.value = lesson.value.analyze_task_id
          analyzeStatus.value = 'PENDING'
          analyzeTimer = setInterval(pollAnalyzeStatus, 2000)
        } else {
          statusPollTimer = setInterval(pollForAnalysisCompletion, 2000)
        }
      }
    } else if (lesson.value.status === 'ready_for_edit') {
      mode.value = CreationMode.PRESENTATION_AUTO
      showSlideEditor.value = true
    } else if (lesson.value.status === 'processing') {
      if (!generating.value) {
        generating.value = true
        stopPolling()
        stopStatusPolling()
        if (lesson.value.video_task_id) {
          taskId.value = lesson.value.video_task_id
          taskStatus.value = 'PENDING'
          pollTimer = setInterval(pollStatus, 2000)
        } else {
          statusPollTimer = setInterval(pollForVideoCompletion, 3000)
        }
      }
    }
  } catch (e: any) {
    error.value = e?.data?.detail ?? 'Не удалось загрузить урок'
  } finally {
    loading.value = false
  }
}

const persistMode = async (m: CreationModeValue) => {
  try {
    await apiFetch(`/lessons/${route.params.id}`, {
      method: 'PUT',
      body: { creation_mode: m },
    })
  } catch {
    // ignore — visual selection still works
  }
}

const onModeSelect = async (m: CreationModeValue) => {
  mode.value = m
  await persistMode(m)
}

const uploadPptx = async () => {
  if (!pptxFile.value) return
  uploading.value = true
  uploadError.value = ''
  try {
    const form = new FormData()
    form.append('file', pptxFile.value)
    form.append('lesson_id', route.params.id as string)

    const result = await apiFetch<any>(`/uploads/pptx?lesson_id=${route.params.id}`, {
      method: 'POST',
      body: form,
    })
    lesson.value.pptx_path = result.file_path
    pptxFile.value = null
  } catch (e: any) {
    uploadError.value = e?.data?.detail ?? 'Ошибка загрузки'
  } finally {
    uploading.value = false
  }
}

const saveScript = async () => {
  savingScript.value = true
  try {
    await apiFetch(`/lessons/${route.params.id}/script`, {
      method: 'PUT',
      body: { script: script.value },
    })
  } finally {
    savingScript.value = false
  }
}

const uploadScriptFile = async () => {
  if (!scriptFile.value) return
  uploadingScript.value = true
  scriptUploadError.value = ''
  try {
    const form = new FormData()
    form.append('file', scriptFile.value)

    const result = await apiFetch<any>(
      `/uploads/script?lesson_id=${route.params.id}`,
      { method: 'POST', body: form },
    )
    script.value = result.script
    scriptFile.value = null
  } catch (e: any) {
    scriptUploadError.value = e?.data?.detail ?? 'Не удалось обработать файл'
  } finally {
    uploadingScript.value = false
  }
}

const stopAnalyzePolling = () => {
  if (analyzeTimer) {
    clearInterval(analyzeTimer)
    analyzeTimer = null
  }
}

const pollAnalyzeStatus = async () => {
  if (!analyzeTaskId.value) return
  try {
    const res = await apiFetch<any>(
      `/lessons/${route.params.id}/analysis-status/${analyzeTaskId.value}`,
    )
    analyzeStatus.value = res.status
    if (res.status === 'PROGRESS') {
      analyzeMeta.value = { step: res.step, done: res.done, total: res.total }
    }
    if (res.status === 'SUCCESS') {
      stopAnalyzePolling()
      analyzing.value = false
      await load()
      showSlideEditor.value = true
    } else if (res.status === 'FAILURE' || res.error) {
      stopAnalyzePolling()
      analyzing.value = false
      analyzeError.value = res.error ?? 'Ошибка анализа'
    }
  } catch {
    // network glitch — keep polling
  }
}

const startAnalyze = async () => {
  if (!lesson.value?.pptx_path) {
    analyzeError.value = 'Сначала загрузите презентацию'
    return
  }
  analyzeError.value = ''
  analyzeMeta.value = null
  analyzing.value = true
  stopAnalyzePolling()
  stopStatusPolling()
  try {
    const res = await apiFetch<any>(`/lessons/${route.params.id}/analyze`, {
      method: 'POST',
    })
    analyzeTaskId.value = res.task_id
    analyzeStatus.value = 'PENDING'
    analyzeTimer = setInterval(pollAnalyzeStatus, 2000)
  } catch (e: any) {
    analyzing.value = false
    analyzeError.value = e?.data?.detail ?? 'Не удалось запустить анализ'
  }
}

const analyzeProgressDone = computed(() => analyzeMeta.value?.done ?? 0)
const analyzeProgressTotal = computed(() => analyzeMeta.value?.total ?? 0)

const stages = computed(() => {
  const base = [
    { key: 'slides',   label: 'Слайды' },
    { key: 'summary',  label: 'Саммари' },
    { key: 'llm',      label: 'Текст' },
    { key: 'tts',      label: 'Озвучка' },
    { key: 'encoding', label: 'Видео' },
  ]
  // Vision/auto mode skips the summary stage — per-slide texts are already in the DB.
  if (mode.value === CreationMode.PRESENTATION_AUTO) {
    return base.filter(s => s.key !== 'summary')
  }
  return base
})

const currentStageIdx = computed(() => {
  if (!taskMeta.value) return 0
  const idx = stages.value.findIndex(s => s.key === taskMeta.value!.step)
  return idx < 0 ? 0 : idx
})

const pipelineStages = computed(() =>
  stages.value.map((s, i) => {
    const stage: { label: string; pct?: number } = { label: s.label }
    if (i === currentStageIdx.value && taskMeta.value && taskMeta.value.total > 0) {
      stage.pct = Math.round((taskMeta.value.done / taskMeta.value.total) * 100)
    }
    return stage
  }),
)

const stopPolling = () => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

const pollStatus = async () => {
  if (!taskId.value) return
  try {
    const res = await apiFetch<any>(`/lessons/${route.params.id}/task-status/${taskId.value}`)
    taskStatus.value = res.status

    if (res.status === 'PROGRESS' && res.meta) {
      taskMeta.value = res.meta
    }

    if (res.status === 'SUCCESS') {
      stopPolling()
      generating.value = false
      await load()
    } else if (res.status === 'FAILURE') {
      stopPolling()
      generating.value = false
      taskError.value = res.result?.error ?? 'Неизвестная ошибка'
    }
  } catch {
    // network glitch — keep polling
  }
}

const cancellingVideo = ref(false)
const warningDismissed = ref(false)

const generateVideo = async () => {
  if (!lesson.value?.pptx_path) {
    taskError.value = 'Сначала загрузите презентацию'
    return
  }

  if (mode.value === CreationMode.PRESENTATION_AND_TEXT && !script.value.trim()) {
    taskError.value = 'Введите текст доклада перед генерацией'
    return
  }

  taskError.value = ''
  taskMeta.value = null
  warningDismissed.value = false
  generating.value = true
  stopPolling()
  stopStatusPolling()

  if (mode.value === CreationMode.PRESENTATION_AND_TEXT) {
    await saveScript()
  }

  try {
    const res = await apiFetch<any>(`/lessons/${route.params.id}/generate-video`, {
      method: 'POST',
      body: { voice: selectedVoice.value },
    })
    taskId.value = res.task_id
    taskStatus.value = 'PENDING'
    pollTimer = setInterval(pollStatus, 3000)
  } catch (e: any) {
    generating.value = false
    taskError.value = e?.data?.detail ?? 'Не удалось запустить генерацию'
  }
}

const cancelVideo = async () => {
  cancellingVideo.value = true
  try {
    await apiFetch(`/lessons/${route.params.id}/cancel-video`, { method: 'POST' })
    stopPolling()
    stopStatusPolling()
    generating.value = false
    taskStatus.value = ''
    taskMeta.value = null
    taskError.value = ''
    await load()
  } catch {
    // ignore
  } finally {
    cancellingVideo.value = false
  }
}

const lessonStatusForBadge = computed(() => {
  if (analyzing.value) return 'analyzing'
  if (generating.value) return 'processing'
  const s = lesson.value?.status
  if (s === 'draft' || s === 'analyzing' || s === 'ready_for_edit'
      || s === 'processing' || s === 'published' || s === 'error') return s
  return 'draft'
})

onMounted(async () => {
  await load()
  await restoreScroll()
})
onUnmounted(() => {
  stopPolling()
  stopAnalyzePolling()
  stopStatusPolling()
})

const isAuto = computed(() => mode.value === CreationMode.PRESENTATION_AUTO)
const isManual = computed(() => mode.value === CreationMode.PRESENTATION_AND_TEXT)
const showPipeline = computed(() => generating.value || taskStatus.value === 'PROGRESS' || lesson.value?.status === 'processing')

const canGenerateVideo = computed(() => {
  if (!lesson.value?.pptx_path) return false
  if (generating.value || lesson.value.status === 'processing') return false
  if (isAuto.value) {
    return lesson.value.status === 'ready_for_edit' || lesson.value.status === 'published'
  }
  if (isManual.value) {
    return script.value.trim().length > 0
  }
  return false
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

    <!-- LLM fallback warning -->
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

    <!-- 1. Choose creation mode -->
    <section class="bg-white rounded-2xl border border-gray-100 p-6 shadow-soft">
      <CreationModeChooser :model-value="mode" @update:model-value="onModeSelect" />
    </section>

    <!-- 2. PPTX upload -->
    <LessonPptxUploader
      v-if="isManual || isAuto"
      :pptx-path="lesson.pptx_path ?? null"
      :uploading="uploading"
      :error="uploadError"
      :selected-file="pptxFile"
      @file-change="pptxFile = $event; uploadError = ''"
      @upload="uploadPptx"
    />

    <!-- 3a. Manual: text editor -->
    <LessonScriptPanel
      v-if="isManual"
      v-model="script"
      :saving="savingScript"
      :open="showScriptEditor"
      :script-file="scriptFile"
      :uploading-script="uploadingScript"
      :script-upload-error="scriptUploadError"
      @toggle="showScriptEditor = !showScriptEditor"
      @save="saveScript"
      @script-file-change="scriptFile = $event; scriptUploadError = ''"
      @upload-script="uploadScriptFile"
    />

    <!-- 3b+3c. Auto: vision analysis + slide editor -->
    <LessonVisionPanel
      v-if="isAuto"
      :has-pptx="!!lesson.pptx_path"
      :analyzing="analyzing"
      :analyze-status="analyzeStatus"
      :analyze-step="analyzeMeta?.step ?? ''"
      :progress-done="analyzeProgressDone"
      :progress-total="analyzeProgressTotal"
      :analyze-error="analyzeError"
      :generating="generating"
      :lesson-status="lesson.status"
      :show-slide-editor="showSlideEditor"
      :lesson-id="String(route.params.id)"
      @start-analyze="startAnalyze"
      @toggle-slide-editor="showSlideEditor = !showSlideEditor"
      @slide-back="showSlideEditor = false"
      @slide-ready="async () => { showSlideEditor = false; await generateVideo() }"
    />

    <!-- 4+5. Video generation + player -->
    <LessonVideoGenerationPanel
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
