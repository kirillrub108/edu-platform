<script setup lang="ts">
import { AlertCircle } from 'lucide-vue-next'

definePageMeta({ middleware: ['auth', 'teacher'], layout: 'workspace' })

const route = useRoute()
const router = useRouter()

const lessonId = computed(() => {
  const id = route.params.id
  return Array.isArray(id) ? id[0] : id
})

const { apiFetch } = useApi()

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

// ── Tab state (query-driven) ───────────────────────────────────────────────────

const VALID_TABS = ['lesson', 'quiz'] as const
type TabId = (typeof VALID_TABS)[number]

const TAB_ITEMS: { id: string; label: string }[] = [
  { id: 'lesson', label: 'Урок' },
  { id: 'quiz', label: 'Тест' },
]

const activeTab = computed<TabId>(() => {
  const t = route.query.tab as string
  return (VALID_TABS as readonly string[]).includes(t) ? (t as TabId) : 'lesson'
})

// Normalize missing or invalid ?tab without adding a history entry.
// Runs once on mount and whenever the query changes.
watch(
  () => route.query.tab,
  () => {
    if (route.query.tab !== activeTab.value) {
      router.replace({ query: { ...route.query, tab: activeTab.value } })
    }
  },
  { immediate: true },
)

const setTab = (id: string) => {
  router.replace({ query: { ...route.query, tab: id } })
}

// ── Video history ─────────────────────────────────────────────────────────────

interface VideoItem {
  id: string
  video_url: string
  voice: string
  creation_mode: string
  is_published: boolean
  created_at: string
}

const videoHistory = ref<VideoItem[]>([])
const previewVideoUrl = ref<string | null>(null)
const publishingVideoId = ref<string | null>(null)

const modeLabels: Record<string, string> = {
  presentation_and_text: 'Слайды + текст',
  presentation_auto: 'Слайды (авто)',
  text_only: 'Только текст',
  prompt: 'Промпт',
}

const voiceLabel = (v: string) => voices.find(x => x.value === v)?.label ?? v

const formatDate = (iso: string) =>
  new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })

const loadVideos = async () => {
  try {
    videoHistory.value = await apiFetch<VideoItem[]>(`/lessons/${lessonId.value}/videos`)
  } catch { /* ignore — no history if endpoint fails */ }
}

const publishVideo = async (video: VideoItem) => {
  if (video.is_published || publishingVideoId.value) return
  publishingVideoId.value = video.id
  try {
    await apiFetch(`/lessons/${lessonId.value}/videos/${video.id}/publish`, { method: 'POST' })
    // Optimistic update of the list.
    videoHistory.value = videoHistory.value.map(v => ({ ...v, is_published: v.id === video.id }))
    // Refresh lesson so video_url and published_video reflect the new state.
    lesson.value = await apiFetch<any>(`/lessons/${lessonId.value}`)
  } catch { /* ignore */ } finally {
    publishingVideoId.value = null
  }
}

// Refresh video list whenever generation finishes (success or failure).
watch(generating, async (newVal, oldVal) => {
  if (oldVal && !newVal) await loadVideos()
})

// ── Quiz results ──────────────────────────────────────────────────────────────

interface QuizResultRow {
  student_id: string
  full_name: string | null
  email: string
  best_score: string | null
  attempts_count: number
  passed: boolean
  last_submitted_at: string | null
}

const quizResults = ref<QuizResultRow[]>([])

const loadQuizResults = async () => {
  try {
    quizResults.value = await apiFetch<QuizResultRow[]>(
      `/lessons/${lessonId.value}/quiz-results`,
    )
  } catch { /* no quiz questions or not yet attempted — leave empty */ }
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────

onMounted(async () => { await load(); await loadVideos(); await loadQuizResults(); await restoreScroll() })

// Both polling loops must outlive tab switches — only stop on full unmount.
onUnmounted(() => { stopVisionPolling(); stopVideoPolling() })

// Stop stale polling when navigating between lessons within the same route pattern.
watch(lessonId, (newId, oldId) => {
  if (newId === oldId) return
  stopVisionPolling()
  stopVideoPolling()
  showSlideEditor.value = false
  warningDismissed.value = false
  videoHistory.value = []
  previewVideoUrl.value = null
  quizResults.value = []
  void load()
  void loadVideos()
  void loadQuizResults()
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

  <div v-else-if="lesson" class="space-y-6">
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

    <UiTabs
      :model-value="activeTab"
      :tabs="TAB_ITEMS"
      @update:model-value="setTab"
    />

    <!-- Урок tab panel — v-show keeps polling timers alive across tab switches -->
    <div
      v-show="activeTab === 'lesson'"
      id="tabpanel-lesson"
      role="tabpanel"
      aria-labelledby="tab-lesson"
      class="space-y-6"
    >
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

      <section
        v-if="videoHistory.length > 0"
        class="bg-white rounded-2xl border border-gray-100 p-6 shadow-soft space-y-4"
      >
        <h2 class="text-lg font-semibold text-gray-900">История генераций</h2>

        <video
          v-if="previewVideoUrl"
          :key="previewVideoUrl"
          :src="previewVideoUrl"
          controls
          autoplay
          class="w-full rounded-xl bg-black"
        />

        <div class="divide-y divide-gray-100">
          <div
            v-for="video in videoHistory"
            :key="video.id"
            class="flex flex-wrap items-center gap-x-4 gap-y-2 py-3"
          >
            <span class="text-sm text-gray-500 w-36 shrink-0 tabular-nums">
              {{ formatDate(video.created_at) }}
            </span>
            <span class="text-sm text-gray-700">{{ voiceLabel(video.voice) }}</span>
            <span class="text-sm text-gray-400">{{ modeLabels[video.creation_mode] ?? video.creation_mode }}</span>
            <span
              v-if="video.is_published"
              class="text-xs bg-violet-100 text-violet-700 px-2 py-0.5 rounded-full font-medium"
            >Опубликовано</span>

            <div class="ml-auto flex items-center gap-2">
              <button
                type="button"
                class="text-sm text-gray-500 hover:text-gray-800 transition px-2 py-1 rounded-lg hover:bg-gray-100"
                title="Предпросмотр"
                @click="previewVideoUrl = video.video_url"
              >▶</button>
              <button
                type="button"
                :disabled="video.is_published || publishingVideoId === video.id"
                class="text-sm font-medium px-3 py-1 rounded-lg border border-violet-200 text-violet-700 hover:bg-violet-50 transition disabled:opacity-40 disabled:pointer-events-none"
                @click="publishVideo(video)"
              >
                <span v-if="publishingVideoId === video.id">…</span>
                <span v-else>Опубликовать</span>
              </button>
            </div>
          </div>
        </div>
      </section>
    </div>

    <!-- Тест tab panel — v-show preserves QuizEditor's polling and save timers -->
    <div
      v-show="activeTab === 'quiz'"
      id="tabpanel-quiz"
      role="tabpanel"
      aria-labelledby="tab-quiz"
      class="space-y-6"
    >
      <QuizEditor :lesson-id="lessonId" />

      <section
        v-if="quizResults.length > 0"
        class="bg-white rounded-2xl border border-gray-100 p-6 shadow-soft space-y-4"
      >
        <h2 class="text-lg font-semibold text-gray-900">Результаты теста</h2>
        <table class="w-full text-sm">
          <thead>
            <tr class="text-left text-gray-500 border-b border-gray-100">
              <th class="pb-2 font-medium">Студент</th>
              <th class="pb-2 font-medium">Email</th>
              <th class="pb-2 font-medium text-center">Лучший</th>
              <th class="pb-2 font-medium text-center">Попыток</th>
              <th class="pb-2 font-medium text-center">Статус</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-50">
            <tr v-for="row in quizResults" :key="row.student_id" class="py-2">
              <td class="py-2 text-gray-800">{{ row.full_name ?? '—' }}</td>
              <td class="py-2 text-gray-500">{{ row.email }}</td>
              <td class="py-2 text-center">
                <span v-if="row.best_score !== null">
                  <span
                    class="font-medium"
                    :class="row.passed ? 'text-green-600' : 'text-red-600'"
                  >{{ Math.round(Number(row.best_score) * 100) }}%</span>
                </span>
                <span v-else class="text-gray-400 italic">—</span>
              </td>
              <td class="py-2 text-center text-gray-600">{{ row.attempts_count }}</td>
              <td class="py-2 text-center">
                <span
                  v-if="row.passed"
                  class="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full"
                >пройден</span>
                <span
                  v-else-if="row.attempts_count > 0"
                  class="text-xs bg-rose-100 text-rose-700 px-2 py-0.5 rounded-full"
                >не сдан</span>
                <span v-else class="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">
                  не приступал
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </div>
  </div>
</template>
