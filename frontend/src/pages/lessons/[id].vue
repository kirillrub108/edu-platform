<script setup lang="ts">
import { CreationMode, type CreationModeValue } from '~/composables/useCreationMode'

definePageMeta({ middleware: ['auth', 'teacher'] })

const route = useRoute()
const { apiFetch } = useApi()

// ── State ─────────────────────────────────────────────────────────────────────
const lesson = ref<any>(null)
const loading = ref(true)
const error = ref('')

// Mode chooser
const mode = ref<CreationModeValue | null>(null)

// PPTX upload
const pptxFile = ref<File | null>(null)
const uploading = ref(false)
const uploadError = ref('')

// Script (manual mode)
const script = ref('')
const savingScript = ref(false)

// Script file upload (txt/md/pdf)
const scriptFile = ref<File | null>(null)
const uploadingScript = ref(false)
const scriptUploadError = ref('')

// Voice
const voices = [
  { value: 'xenia',   label: 'Ксения (жен.)' },
  { value: 'baya',    label: 'Байя (жен.)' },
  { value: 'kseniya', label: 'Ксения-2 (жен.)' },
  { value: 'aidar',   label: 'Айдар (муж.)' },
  { value: 'eugene',  label: 'Евгений (муж.)' },
]
const selectedVoice = ref<string>('xenia')

// Vision analysis state
const analyzeTaskId = ref<string | null>(null)
const analyzeStatus = ref<string>('')
const analyzeMeta = ref<{ step?: string; done?: number; total?: number } | null>(null)
const analyzeError = ref('')
const analyzing = ref(false)
let analyzeTimer: ReturnType<typeof setInterval> | null = null

const showSlideEditor = ref(false)

// Video generation
const taskId = ref<string | null>(null)
const taskStatus = ref<string>('')
const taskMeta = ref<{ step: string; done: number; total: number } | null>(null)
const taskError = ref('')
const generating = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

// ── Load lesson ───────────────────────────────────────────────────────────────
const load = async () => {
  loading.value = true
  error.value = ''
  try {
    lesson.value = await apiFetch<any>(`/lessons/${route.params.id}`)
    script.value = lesson.value.script ?? lesson.value.text_content ?? ''
    if (lesson.value.creation_mode) {
      mode.value = lesson.value.creation_mode as CreationModeValue
    }
    if (lesson.value.status === 'ready_for_edit' || lesson.value.status === 'analyzing') {
      mode.value = CreationMode.PRESENTATION_AUTO
      if (lesson.value.status === 'ready_for_edit') {
        showSlideEditor.value = true
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

// ── PPTX upload ───────────────────────────────────────────────────────────────
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

// ── Manual script ─────────────────────────────────────────────────────────────
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

// ── Vision analysis flow ──────────────────────────────────────────────────────
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

const analyzeProgressPct = computed(() => {
  const done = analyzeMeta.value?.done ?? 0
  const total = analyzeMeta.value?.total ?? 0
  return total > 0 ? Math.round((done / total) * 100) : 0
})

// ── Video generation ──────────────────────────────────────────────────────────
const stages = [
  { key: 'slides',   label: 'Слайды' },
  { key: 'llm',      label: 'Текст' },
  { key: 'tts',      label: 'Озвучка' },
  { key: 'encoding', label: 'Видео' },
]

const currentStageIdx = computed(() => {
  if (!taskMeta.value) return -1
  return stages.findIndex(s => s.key === taskMeta.value!.step)
})

const stageState = (idx: number): 'pending' | 'active' | 'done' => {
  const cur = currentStageIdx.value
  if (cur < 0) return 'pending'
  if (idx < cur) return 'done'
  if (idx === cur) return 'active'
  return 'pending'
}

const stageLabelClass = (idx: number): string => {
  const s = stageState(idx)
  if (s === 'done')   return 'text-brand'
  if (s === 'active') return 'text-brand font-medium'
  return 'text-gray-400'
}

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

// ── Status helpers ────────────────────────────────────────────────────────────
const statusLabel: Record<string, string> = {
  draft: 'Черновик',
  analyzing: 'Анализируется',
  ready_for_edit: 'Готов к редактированию',
  processing: 'Генерируется',
  published: 'Опубликован',
  error: 'Ошибка',
}

const statusColor: Record<string, string> = {
  draft: 'bg-gray-100 text-gray-600',
  analyzing: 'bg-blue-100 text-blue-700',
  ready_for_edit: 'bg-indigo-100 text-indigo-700',
  processing: 'bg-yellow-100 text-yellow-700',
  published: 'bg-green-100 text-green-700',
  error: 'bg-red-100 text-red-700',
}

onMounted(load)
onUnmounted(() => {
  stopPolling()
  stopAnalyzePolling()
})

const isAuto = computed(() => mode.value === CreationMode.PRESENTATION_AUTO)
const isManual = computed(() => mode.value === CreationMode.PRESENTATION_AND_TEXT)
</script>

<template>
  <div v-if="loading" class="text-gray-500">Загрузка…</div>
  <div v-else-if="error" class="text-red-600">{{ error }}</div>

  <div v-else-if="lesson" class="space-y-8 max-w-4xl">

    <!-- Header -->
    <div>
      <NuxtLink to="/courses" class="text-sm text-brand hover:underline block mb-2">← Назад к курсам</NuxtLink>
      <div class="flex items-center gap-3 flex-wrap">
        <h1 class="text-2xl font-semibold">{{ lesson.title }}</h1>
        <span
          class="text-xs px-2 py-1 rounded-full font-medium"
          :class="statusColor[lesson.status]"
        >
          {{ statusLabel[lesson.status] ?? lesson.status }}
        </span>
      </div>
    </div>

    <!-- Slide editor takes over when active -->
    <section v-if="showSlideEditor" class="bg-white border rounded-xl p-5">
      <SlideTextEditor
        :lesson-id="String(route.params.id)"
        @back="showSlideEditor = false"
        @ready="async () => { showSlideEditor = false; await generateVideo() }"
      />
    </section>

    <template v-else>

      <!-- ── 1. Choose creation mode ── -->
      <section class="bg-white border rounded-xl p-5">
        <CreationModeChooser
          :model-value="mode"
          @update:model-value="onModeSelect"
        />
      </section>

      <!-- ── 2. PPTX upload (both modes) ── -->
      <section v-if="isManual || isAuto" class="bg-white border rounded-xl p-5">
        <h2 class="font-semibold mb-1">Презентация</h2>
        <p class="text-sm text-gray-500 mb-4">Загрузите PPTX, PPT или PDF-файл со слайдами.</p>

        <div v-if="lesson.pptx_path" class="flex items-center gap-2 mb-3 text-sm text-green-700 bg-green-50 border border-green-200 rounded px-3 py-2">
          <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
          </svg>
          <span class="truncate">{{ lesson.pptx_path.split('/').pop() }}</span>
        </div>

        <div class="flex gap-2 items-center">
          <label class="cursor-pointer px-4 py-2 border rounded text-sm hover:bg-gray-50 transition">
            {{ pptxFile ? pptxFile.name : 'Выбрать файл' }}
            <input type="file" accept=".pptx,.ppt,.pdf" class="hidden" @change="onFileChange" />
          </label>
          <button
            v-if="pptxFile"
            class="px-4 py-2 bg-brand text-white rounded text-sm disabled:opacity-50"
            :disabled="uploading"
            @click="uploadPptx"
          >
            {{ uploading ? 'Загрузка…' : 'Загрузить' }}
          </button>
        </div>
        <p v-if="uploadError" class="mt-2 text-sm text-red-600">{{ uploadError }}</p>
      </section>

      <!-- ── 3a. Manual: text editor ── -->
      <section v-if="isManual" class="bg-white border rounded-xl p-5">
        <h2 class="font-semibold mb-1">Текст доклада</h2>
        <p class="text-sm text-gray-500 mb-4">
          Введите полный текст или загрузите файл. LLM разобьёт его по слайдам.
        </p>

        <div class="flex flex-wrap gap-2 items-center mb-3">
          <label class="cursor-pointer px-3 py-1.5 border rounded text-sm hover:bg-gray-50 transition inline-flex items-center gap-2">
            <svg class="w-4 h-4 text-gray-500" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v12m0 0l-4-4m4 4l4-4M4 20h16"/>
            </svg>
            {{ scriptFile ? scriptFile.name : 'Загрузить из файла' }}
            <input
              type="file"
              accept=".txt,.md,.markdown,.pdf,.docx,.doc,.rtf,.odt,.html,.htm"
              class="hidden"
              @change="onScriptFileChange"
            />
          </label>
          <button
            v-if="scriptFile"
            class="px-3 py-1.5 bg-brand text-white rounded text-sm disabled:opacity-50"
            :disabled="uploadingScript"
            @click="uploadScriptFile"
          >
            {{ uploadingScript ? 'Извлечение…' : 'Извлечь текст' }}
          </button>
          <span class="text-xs text-gray-400">TXT, MD, PDF, DOCX, DOC, RTF, ODT, HTML</span>
        </div>
        <p v-if="scriptUploadError" class="mb-2 text-sm text-red-600">{{ scriptUploadError }}</p>

        <textarea
          v-model="script"
          rows="8"
          placeholder="Введите текст доклада…"
          class="w-full border rounded px-3 py-2 text-sm resize-y focus:outline-none focus:ring-2 focus:ring-brand/40"
        />
        <div class="flex justify-between items-center mt-2">
          <span class="text-xs text-gray-400">{{ script.split(/\s+/).filter(Boolean).length }} слов</span>
          <button
            class="px-4 py-1.5 border rounded text-sm hover:bg-gray-50 transition disabled:opacity-50"
            :disabled="savingScript"
            @click="saveScript"
          >
            {{ savingScript ? 'Сохранение…' : 'Сохранить' }}
          </button>
        </div>
      </section>

      <!-- ── 3b. Auto: vision analysis ── -->
      <section v-if="isAuto" class="bg-white border rounded-xl p-5">
        <h2 class="font-semibold mb-1">Автогенерация текста по слайдам</h2>
        <p class="text-sm text-gray-500 mb-4">
          Vision LLM проанализирует каждый слайд и напишет развёрнутый текст озвучки.
        </p>

        <div v-if="analyzing || analyzeStatus === 'PROGRESS'" class="mb-4">
          <div class="text-sm text-gray-700 mb-2">
            <template v-if="analyzeMeta?.step === 'slides'">Подготовка слайдов…</template>
            <template v-else-if="analyzeMeta?.step === 'vision'">
              Анализируется слайд {{ analyzeMeta?.done ?? 0 }} из {{ analyzeMeta?.total ?? '…' }}
            </template>
            <template v-else>Запуск анализа…</template>
          </div>
          <div class="h-2 bg-gray-100 rounded-full overflow-hidden">
            <div
              class="h-full bg-brand transition-all"
              :style="{ width: `${analyzeProgressPct}%` }"
            />
          </div>
        </div>

        <p v-if="analyzeError" class="mb-3 text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">
          {{ analyzeError }}
        </p>

        <div class="flex gap-2 flex-wrap">
          <button
            class="px-4 py-2 bg-brand text-white rounded text-sm disabled:opacity-50"
            :disabled="!lesson.pptx_path || analyzing"
            @click="startAnalyze"
          >
            {{ analyzing ? 'Анализ…' : (lesson.status === 'ready_for_edit' ? 'Перезапустить анализ' : 'Запустить анализ') }}
          </button>
          <button
            v-if="lesson.status === 'ready_for_edit'"
            class="px-4 py-2 border rounded text-sm hover:bg-gray-50"
            @click="showSlideEditor = true"
          >
            Открыть редактор текста →
          </button>
        </div>
      </section>

      <!-- ── 4. Generate video ── -->
      <section v-if="isManual || isAuto" class="bg-white border rounded-xl p-5">
        <h2 class="font-semibold mb-1">Генерация видео</h2>
        <p class="text-sm text-gray-500 mb-4">
          Запустите пайплайн: слайды + озвучка → MP4. Займёт 1–5 минут.
        </p>

        <div class="mb-4 max-w-xs">
          <label class="block text-sm text-gray-700 mb-1">Голос озвучки</label>
          <div class="relative">
            <select
              v-model="selectedVoice"
              :disabled="generating || lesson.status === 'processing'"
              class="w-full border rounded px-3 py-2 text-sm bg-white appearance-none pr-9 focus:outline-none focus:ring-2 focus:ring-brand/40 disabled:opacity-50"
            >
              <option v-for="v in voices" :key="v.value" :value="v.value">{{ v.label }}</option>
            </select>
            <svg class="w-4 h-4 absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7"/>
            </svg>
          </div>
        </div>

        <div v-if="generating || taskStatus === 'PROGRESS'" class="mb-5">
          <div class="flex items-start">
            <template v-for="(stage, idx) in stages" :key="stage.key">
              <div class="flex flex-col items-center flex-none">
                <template v-if="stageState(idx) === 'active'">
                  <svg class="w-7 h-7 animate-spin text-brand" viewBox="0 0 28 28" fill="none" style="animation-duration:1.1s">
                    <circle cx="14" cy="14" r="11" stroke="currentColor" stroke-opacity="0.18" stroke-width="2.5"/>
                    <circle cx="14" cy="14" r="11" stroke="currentColor" stroke-width="2.5"
                      stroke-dasharray="17 52" stroke-linecap="round"
                      transform="rotate(-90 14 14)"/>
                  </svg>
                </template>
                <template v-else-if="stageState(idx) === 'done'">
                  <div class="w-7 h-7 rounded-full bg-brand border-2 border-brand flex items-center justify-center transition-all duration-300">
                    <svg class="w-3.5 h-3.5 text-white" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/>
                    </svg>
                  </div>
                </template>
                <template v-else>
                  <div class="w-7 h-7 rounded-full bg-white border-2 border-gray-300 flex items-center justify-center text-xs font-semibold text-gray-400">
                    {{ idx + 1 }}
                  </div>
                </template>

                <span class="text-[10px] mt-1 text-center leading-tight w-14 transition-colors duration-300" :class="stageLabelClass(idx)">
                  {{ stage.label }}
                </span>
              </div>
              <div
                v-if="idx < stages.length - 1"
                class="flex-1 h-0.5 mt-3.5 mx-1 transition-colors duration-500"
                :class="stageState(idx) === 'done' ? 'bg-brand' : 'bg-gray-200'"
              />
            </template>
          </div>
        </div>

        <p v-if="taskError" class="mb-3 text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">
          {{ taskError }}
        </p>

        <button
          class="px-5 py-2 bg-brand text-white rounded font-medium disabled:opacity-50 transition"
          :disabled="generating || lesson.status === 'processing'"
          @click="generateVideo"
        >
          <span v-if="generating || lesson.status === 'processing'">Генерируется…</span>
          <span v-else-if="lesson.status === 'published'">Перегенерировать</span>
          <span v-else>Создать видео</span>
        </button>
      </section>

      <!-- ── 5. Video player ── -->
      <section v-if="lesson.status === 'published' && lesson.video_url" class="bg-white border rounded-xl p-5">
        <h2 class="font-semibold mb-3">Готовое видео</h2>
        <video
          :src="lesson.video_url"
          controls
          class="w-full rounded"
        />
        <a
          :href="lesson.video_url"
          target="_blank"
          class="mt-2 inline-block text-sm text-brand hover:underline"
        >
          Открыть в новой вкладке
        </a>
      </section>

    </template>
  </div>
</template>
