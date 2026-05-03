<script setup lang="ts">
definePageMeta({ middleware: ['auth', 'teacher'] })

const route = useRoute()
const { apiFetch } = useApi()

// ── State ─────────────────────────────────────────────────────────────────────
const lesson = ref<any>(null)
const loading = ref(true)
const error = ref('')

// PPTX upload
const pptxFile = ref<File | null>(null)
const uploading = ref(false)
const uploadError = ref('')

// Script
const script = ref('')
const savingScript = ref(false)

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
  } catch (e: any) {
    error.value = e?.data?.detail ?? 'Не удалось загрузить урок'
  } finally {
    loading.value = false
  }
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

// ── Script ────────────────────────────────────────────────────────────────────
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

// ── Video generation & polling ────────────────────────────────────────────────
const stepLabel: Record<string, string> = {
  slides: 'Конвертация слайдов',
  llm: 'Разбивка текста по слайдам',
  tts: 'Генерация озвучки',
  encoding: 'Кодирование видео',
}

const progressPercent = computed(() => {
  if (!taskMeta.value || !taskMeta.value.total) return 0
  return Math.round((taskMeta.value.done / taskMeta.value.total) * 100)
})

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
    taskError.value = 'Сначала загрузите PPTX-файл'
    return
  }
  if (!script.value.trim()) {
    taskError.value = 'Введите текст доклада перед генерацией'
    return
  }

  taskError.value = ''
  taskMeta.value = null
  generating.value = true

  // Save script first
  await saveScript()

  try {
    const res = await apiFetch<any>(`/lessons/${route.params.id}/generate-video`, {
      method: 'POST',
      body: {},
    })
    taskId.value = res.task_id
    taskStatus.value = 'PENDING'
    pollTimer = setInterval(pollStatus, 3000)
  } catch (e: any) {
    generating.value = false
    taskError.value = e?.data?.detail ?? 'Не удалось запустить генерацию'
  }
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────
const statusLabel: Record<string, string> = {
  draft: 'Черновик',
  processing: 'Генерируется',
  published: 'Опубликован',
  error: 'Ошибка',
}

const statusColor: Record<string, string> = {
  draft: 'bg-gray-100 text-gray-600',
  processing: 'bg-yellow-100 text-yellow-700',
  published: 'bg-green-100 text-green-700',
  error: 'bg-red-100 text-red-700',
}

onMounted(load)
onUnmounted(stopPolling)
</script>

<template>
  <div v-if="loading" class="text-gray-500">Загрузка…</div>
  <div v-else-if="error" class="text-red-600">{{ error }}</div>

  <div v-else-if="lesson" class="max-w-2xl space-y-8">

    <!-- Header -->
    <div>
      <NuxtLink to="/courses" class="text-sm text-brand hover:underline block mb-2">← Назад к курсам</NuxtLink>
      <div class="flex items-center gap-3">
        <h1 class="text-2xl font-semibold">{{ lesson.title }}</h1>
        <span
          class="text-xs px-2 py-1 rounded-full font-medium"
          :class="statusColor[lesson.status]"
        >
          {{ statusLabel[lesson.status] ?? lesson.status }}
        </span>
      </div>
    </div>

    <!-- ── 1. PPTX upload ── -->
    <section class="bg-white border rounded-lg p-5">
      <h2 class="font-semibold mb-1">1. Презентация</h2>
      <p class="text-sm text-gray-500 mb-4">Загрузите PPTX, PPT или PDF-файл с вашими слайдами.</p>

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

    <!-- ── 2. Script ── -->
    <section class="bg-white border rounded-lg p-5">
      <h2 class="font-semibold mb-1">2. Текст доклада</h2>
      <p class="text-sm text-gray-500 mb-4">
        Напишите полный текст, который будет озвучен. LLM автоматически разобьёт его по слайдам.
      </p>
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

    <!-- ── 3. Generate ── -->
    <section class="bg-white border rounded-lg p-5">
      <h2 class="font-semibold mb-1">3. Генерация видео</h2>
      <p class="text-sm text-gray-500 mb-4">
        Запустите пайплайн: слайды + озвучка → MP4. Займёт 1–5 минут.
      </p>

      <!-- Progress -->
      <div v-if="generating || taskStatus === 'PROGRESS'" class="mb-4">
        <div class="flex justify-between text-sm mb-1">
          <span class="text-gray-700">{{ taskMeta ? (stepLabel[taskMeta.step] ?? taskMeta.step) : 'Запуск…' }}</span>
          <span class="text-gray-500">{{ progressPercent }}%</span>
        </div>
        <div class="w-full bg-gray-200 rounded-full h-2">
          <div
            class="bg-brand h-2 rounded-full transition-all duration-300"
            :style="{ width: progressPercent + '%' }"
          />
        </div>
        <p v-if="taskMeta" class="text-xs text-gray-400 mt-1">
          {{ taskMeta.done }} / {{ taskMeta.total }}
        </p>
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

    <!-- ── 4. Video player ── -->
    <section v-if="lesson.status === 'published' && lesson.video_url" class="bg-white border rounded-lg p-5">
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

  </div>
</template>
