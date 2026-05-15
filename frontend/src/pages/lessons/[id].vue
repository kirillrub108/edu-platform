<script setup lang="ts">
import { ChevronLeft, ChevronDown, Upload, FileText, Sparkles, Video, CheckCircle2, ArrowDown, AlertCircle, Square } from 'lucide-vue-next'
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

const onFileChange = (e: Event) => {
  const input = e.target as HTMLInputElement
  pptxFile.value = input.files?.[0] ?? null
  uploadError.value = ''
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

const onScriptFileChange = (e: Event) => {
  const input = e.target as HTMLInputElement
  scriptFile.value = input.files?.[0] ?? null
  scriptUploadError.value = ''
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

const cancellingVideo = ref(false)

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

    <!-- Header -->
    <div>
      <NuxtLink
        to="/dashboard"
        class="inline-flex items-center gap-1 text-sm text-violet-700 hover:text-violet-600 font-medium transition mb-2"
      >
        <ChevronLeft class="w-4 h-4" />
        Назад к курсам
      </NuxtLink>
      <div class="flex items-center gap-3 flex-wrap">
        <h1 class="text-2xl font-semibold text-gray-900">{{ lesson.title }}</h1>
        <StatusBadge :status="lessonStatusForBadge" />
      </div>
    </div>

      <!-- 1. Choose creation mode -->
      <section class="bg-white rounded-2xl border border-gray-100 p-6 shadow-soft">
        <CreationModeChooser :model-value="mode" @update:model-value="onModeSelect" />
      </section>

      <!-- 2. PPTX upload -->
      <section v-if="isManual || isAuto" class="bg-white rounded-2xl border border-gray-100 p-6 shadow-soft">
        <h2 class="text-lg font-semibold text-gray-900 mb-1">Презентация</h2>
        <p class="text-sm text-gray-500 mb-4">Загрузите PPTX, PPT или PDF-файл со слайдами.</p>

        <div
          v-if="lesson.pptx_path"
          class="flex items-center gap-2 mb-3 text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-xl px-3 py-2"
        >
          <CheckCircle2 class="w-4 h-4 shrink-0" />
          <span class="truncate">{{ lesson.pptx_path.split('/').pop() }}</span>
        </div>

        <div class="flex gap-2 items-center flex-wrap">
          <label class="cursor-pointer inline-flex items-center gap-2 px-4 py-2 border border-gray-200 rounded-xl text-sm font-medium text-gray-700 hover:bg-violet-50 hover:border-violet-200 hover:text-violet-700 transition">
            <Upload class="w-4 h-4" />
            {{ pptxFile ? pptxFile.name : 'Выбрать файл' }}
            <input type="file" accept=".pptx,.ppt,.pdf" class="hidden" @change="onFileChange" />
          </label>
          <UiButton
            v-if="pptxFile"
            variant="primary"
            size="sm"
            :loading="uploading"
            @click="uploadPptx"
          >
            Загрузить
          </UiButton>
        </div>
        <p v-if="uploadError" class="mt-2 text-sm text-rose-600">{{ uploadError }}</p>
      </section>

      <!-- 3a. Manual: text editor -->
      <section v-if="isManual" class="bg-white rounded-2xl border border-gray-100 shadow-soft overflow-hidden">
        <button
          type="button"
          class="w-full flex items-center justify-between px-6 py-4 hover:bg-gray-50 transition"
          @click="showScriptEditor = !showScriptEditor"
        >
          <div class="text-left">
            <h2 class="text-lg font-semibold text-gray-900">Текст доклада</h2>
            <p class="text-sm text-gray-500">Введите полный текст или загрузите файл. LLM разобьёт его по слайдам.</p>
          </div>
          <ChevronDown
            class="w-5 h-5 text-gray-400 transition-transform duration-200 shrink-0"
            :class="{ 'rotate-180': showScriptEditor }"
          />
        </button>
        <div v-if="showScriptEditor" class="px-6 pb-6">
          <div class="flex flex-wrap gap-2 items-center mb-3">
            <label class="cursor-pointer inline-flex items-center gap-2 px-3 py-1.5 border border-gray-200 rounded-lg text-sm text-gray-700 hover:bg-violet-50 hover:border-violet-200 hover:text-violet-700 transition">
              <FileText class="w-4 h-4" />
              {{ scriptFile ? scriptFile.name : 'Загрузить из файла' }}
              <input
                type="file"
                accept=".txt,.md,.markdown,.pdf,.docx,.doc,.rtf,.odt,.html,.htm"
                class="hidden"
                @change="onScriptFileChange"
              />
            </label>
            <UiButton
              v-if="scriptFile"
              variant="primary"
              size="sm"
              :loading="uploadingScript"
              @click="uploadScriptFile"
            >
              Извлечь текст
            </UiButton>
            <span class="text-xs text-gray-400">TXT, MD, PDF, DOCX, DOC, RTF, ODT, HTML</span>
          </div>
          <p v-if="scriptUploadError" class="mb-2 text-sm text-rose-600">{{ scriptUploadError }}</p>

          <textarea
            v-model="script"
            rows="8"
            placeholder="Введите текст доклада…"
            class="w-full bg-white px-4 py-3 text-sm leading-relaxed border border-gray-200 rounded-xl resize-y focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400 transition"
          />
          <div class="flex justify-between items-center mt-2">
            <span class="text-xs text-gray-500">
              {{ script.split(/\s+/).filter(Boolean).length }} слов
            </span>
            <UiButton
              variant="secondary"
              size="sm"
              :loading="savingScript"
              @click="saveScript"
            >
              Сохранить
            </UiButton>
          </div>
        </div>
      </section>

      <!-- 3b. Auto: vision analysis -->
      <section v-if="isAuto" class="bg-white rounded-2xl border border-gray-100 p-6 shadow-soft">
        <h2 class="text-lg font-semibold text-gray-900 mb-1">Автогенерация текста по слайдам</h2>
        <p class="text-sm text-gray-500 mb-4">
          Vision LLM проанализирует каждый слайд и напишет развёрнутый текст озвучки.
        </p>

        <div v-if="analyzing || analyzeStatus === 'PROGRESS'" class="mb-4">
          <div class="text-sm text-violet-700 mb-2 flex items-center gap-1.5">
            <Sparkles class="w-4 h-4 animate-pulse" />
            <template v-if="analyzeMeta?.step === 'slides'">Подготовка слайдов…</template>
            <template v-else-if="analyzeMeta?.step === 'vision'">
              Анализируется слайд {{ analyzeProgressDone }} из {{ analyzeProgressTotal || '…' }}
            </template>
            <template v-else>Запуск анализа…</template>
          </div>
          <ProgressBar
            :value="analyzeProgressDone"
            :total="analyzeProgressTotal"
            :indeterminate="analyzeProgressTotal === 0"
          />
        </div>

        <div
          v-if="analyzeError"
          class="flex items-start gap-2 mb-3 text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-xl px-3 py-2"
        >
          <AlertCircle class="w-4 h-4 shrink-0 mt-0.5" />
          <span>{{ analyzeError }}</span>
        </div>

        <div class="flex gap-2 flex-wrap">
          <UiButton
            variant="primary"
            :loading="analyzing"
            :disabled="!lesson.pptx_path || generating || lesson.status === 'processing'"
            @click="startAnalyze"
          >
            <template #icon><Sparkles class="w-4 h-4" /></template>
            {{ (lesson.status === 'ready_for_edit' || lesson.status === 'published') ? 'Перезапустить анализ' : 'Запустить анализ' }}
          </UiButton>
        </div>
      </section>

      <!-- 3c. Analysis results (collapsible) -->
      <section
        v-if="isAuto && (lesson.status === 'ready_for_edit' || lesson.status === 'published')"
        class="bg-white rounded-2xl border border-gray-100 shadow-soft overflow-hidden"
      >
        <button
          type="button"
          class="w-full flex items-center justify-between px-6 py-4 hover:bg-gray-50 transition"
          @click="showSlideEditor = !showSlideEditor"
        >
          <div class="text-left">
            <h2 class="text-lg font-semibold text-gray-900">Результаты анализа</h2>
            <p class="text-sm text-gray-500">Текст озвучки по слайдам — можно редактировать</p>
          </div>
          <ChevronDown
            class="w-5 h-5 text-gray-400 transition-transform duration-200 shrink-0"
            :class="{ 'rotate-180': showSlideEditor }"
          />
        </button>
        <div v-if="showSlideEditor" class="px-6 pb-6">
          <SlideTextEditor
            :lesson-id="String(route.params.id)"
            @back="showSlideEditor = false"
            @ready="async () => { showSlideEditor = false; await generateVideo() }"
          />
        </div>
      </section>

      <!-- 4. Generate video -->
      <section v-if="isManual || isAuto" class="bg-white rounded-2xl border border-gray-100 p-6 shadow-soft">
        <h2 class="text-lg font-semibold text-gray-900 mb-1">Генерация видео</h2>
        <p class="text-sm text-gray-500 mb-5">
          Запустите пайплайн: слайды + озвучка → MP4. Займёт 1–5 минут.
        </p>

        <div class="mb-5 max-w-xs">
          <label class="block text-sm font-medium text-gray-700 mb-1.5">Голос озвучки</label>
          <div class="relative">
            <select
              v-model="selectedVoice"
              :disabled="generating || lesson.status === 'processing'"
              class="w-full bg-white border border-gray-200 rounded-xl px-4 py-2.5 text-sm appearance-none pr-9 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400 disabled:opacity-50 transition"
            >
              <option v-for="v in voices" :key="v.value" :value="v.value">{{ v.label }}</option>
            </select>
            <ArrowDown class="w-4 h-4 absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
          </div>
        </div>

        <div v-if="showPipeline" class="mb-5 px-2">
          <PipelineStages :stages="pipelineStages" :current="currentStageIdx" />
        </div>

        <div
          v-if="taskError"
          class="flex items-start gap-2 mb-3 text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-xl px-3 py-2"
        >
          <AlertCircle class="w-4 h-4 shrink-0 mt-0.5" />
          <span>{{ taskError }}</span>
        </div>

        <div class="flex gap-2 flex-wrap items-center">
          <UiButton
            variant="primary"
            :loading="generating || lesson.status === 'processing'"
            :disabled="!canGenerateVideo"
            @click="generateVideo"
          >
            <template #icon><Video class="w-4 h-4" /></template>
            <span v-if="generating || lesson.status === 'processing'">Генерируется…</span>
            <span v-else-if="lesson.status === 'published'">Перегенерировать</span>
            <span v-else>Создать видео</span>
          </UiButton>
          <UiButton
            v-if="generating || lesson.status === 'processing'"
            variant="secondary"
            :loading="cancellingVideo"
            @click="cancelVideo"
          >
            <template #icon><Square class="w-4 h-4" /></template>
            Остановить
          </UiButton>
        </div>
        <p v-if="!canGenerateVideo && !generating && lesson.status !== 'processing'" class="mt-2 text-xs text-gray-400">
          <template v-if="!lesson.pptx_path">Сначала загрузите презентацию</template>
          <template v-else-if="isAuto && analyzing">Дождитесь завершения анализа</template>
          <template v-else-if="isAuto && lesson.status !== 'ready_for_edit' && lesson.status !== 'published'">Сначала запустите анализ презентации</template>
          <template v-else-if="isManual && !script.trim()">Введите текст доклада</template>
        </p>
      </section>

      <!-- 5. Video player -->
      <section
        v-if="lesson.status === 'published' && lesson.video_url"
        class="bg-white rounded-2xl border border-gray-100 p-6 shadow-soft"
      >
        <h2 class="text-lg font-semibold text-gray-900 mb-3">Готовое видео</h2>
        <video :src="lesson.video_url" controls class="w-full rounded-xl bg-black" />
        <a
          :href="lesson.video_url"
          target="_blank"
          class="mt-3 inline-block text-sm text-violet-700 hover:text-violet-600 font-medium transition"
        >
          Открыть в новой вкладке →
        </a>
      </section>
  </div>
</template>
