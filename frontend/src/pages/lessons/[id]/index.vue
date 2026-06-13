<script setup lang="ts">
import { AlertCircle, MessageSquare, X } from 'lucide-vue-next'
import type { Comment } from '~/stores/comments'

definePageMeta({ middleware: ['auth', 'teacher'], layout: 'workspace' })

const route = useRoute()
const router = useRouter()

const lessonId = computed(() => {
  const id = route.params.id
  return Array.isArray(id) ? id[0] : id
})

const { apiFetch } = useApi()
const commentsStore = useCommentsStore()

// Teacher owns this lesson's course, so they may moderate any comment here.
// Backend comment_service.delete_comment enforces the same ownership rule.
const canDeleteComment = (_c: Comment): boolean => true

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
  videoFile, uploadingVideo, videoUploadError,
  isAuto, isManual, isVideoUpload,
  load, onModeSelect, uploadPptx, uploadScriptFile, uploadVideo, flushScript,
} = useLessonData(lessonId)

const {
  startAnalysis, cancelAnalysis, analyzing, analyzeMeta, analyzeStatus, analyzeError,
  cancellingAnalysis, stopPolling: stopVisionPolling,
  creditsSpent: analyzeCreditsSpent, creditsReserved: analyzeCreditsReserved,
  billedVia: analyzeBilledVia, needTopup: analyzeNeedTopup,
} = useVisionAnalysis(lessonId, lesson, visionPanelRef, showSlideEditor)

const {
  generateVideo: _generateVideo, cancelVideo, generating, taskError,
  selectedVoice, voices, canGenerateVideo, showPipeline,
  pipelineStages, currentStageIdx, cancellingVideo, stopPolling: stopVideoPolling,
  creditsSpent, creditsReserved, billedVia, needTopup, cancelled,
} = useVideoGeneration(lessonId, lesson, mode, script, flushScript, isAuto, showSlideEditor)

// Block AI actions behind email verification — opens the verify prompt and
// never hits the backend when the user is unverified.
const { ensureVerified } = useAiGuard()

// ── Generation cost confirmation modal ─────────────────────────────────────────

const estimateData = ref<any | null>(null)
const estimateLoading = ref(false)
const costModalOpen = ref(false)
const costModalKind = ref<'video' | 'analyze'>('video')
let pendingAction: (() => unknown) | null = null

const openCostModal = async (kind: 'video' | 'analyze', action: () => unknown) => {
  costModalKind.value = kind
  pendingAction = action
  estimateData.value = null
  estimateLoading.value = true
  costModalOpen.value = true
  try {
    estimateData.value = await apiFetch<any>(`/lessons/${lessonId.value}/generation-estimate`)
  } catch {
    // Estimate failed — don't block the user, run directly without the modal.
    costModalOpen.value = false
    const act = pendingAction
    pendingAction = null
    await act?.()
  } finally {
    estimateLoading.value = false
  }
}

const onCostConfirm = async () => {
  costModalOpen.value = false
  const act = pendingAction
  pendingAction = null
  await act?.()
}

const onCostClose = () => {
  costModalOpen.value = false
  pendingAction = null
}

// Reset the LLM-fallback warning banner each time generation starts.
const generateVideo = () =>
  ensureVerified(() =>
    openCostModal('video', async () => { warningDismissed.value = false; await _generateVideo() }),
  )
const guardedStartAnalysis = () =>
  ensureVerified(() => openCostModal('analyze', startAnalysis))

const lessonStatusForBadge = computed(() => {
  if (analyzing.value) return 'analyzing'
  if (generating.value) return 'processing'
  const s = lesson.value?.status
  return ['draft', 'analyzing', 'ready_for_edit', 'processing', 'published', 'error'].includes(s) ? s : 'draft'
})

// ── Tab state (query-driven) ───────────────────────────────────────────────────

const VALID_TABS = ['lesson', 'quiz', 'assignments'] as const
type TabId = (typeof VALID_TABS)[number]

const TAB_ITEMS: { id: string; label: string }[] = [
  { id: 'lesson', label: 'Урок' },
  { id: 'quiz', label: 'Тест' },
  { id: 'assignments', label: 'Задания' },
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

// Declared above the workflow steps: the step list/status derive from it and the
// workflowSteps watcher evaluates its getter eagerly at setup.
const videoHistory = ref<VideoItem[]>([])

// ── Урок workflow steps (wizard) ───────────────────────────────────────────────
// The long creation flow is split into steps; only the active step's panel is
// shown on the left while the others stay mounted (v-show) so analysis/generation
// polling and the vision snapshot ref are never torn down by a step switch.

type StepKey = 'mode' | 'video' | 'presentation' | 'script' | 'generate' | 'history'

const modeLabels: Record<string, string> = {
  presentation_and_text: 'Слайды + текст',
  presentation_auto: 'Слайды (авто)',
  text_only: 'Только текст',
  prompt: 'Промпт',
  video_upload: 'Готовое видео',
}

const TONE = {
  done: 'bg-emerald-100 text-emerald-700',
  wait: 'bg-amber-100 text-amber-700',
  idle: 'bg-gray-100 text-gray-500',
  mode: 'bg-violet-100 text-violet-700',
}

const isStepDone = (key: StepKey): boolean => {
  switch (key) {
    case 'video':
    case 'generate':
      return !!lesson.value?.video_url
    case 'presentation':
      return !!lesson.value?.pptx_path
    case 'script':
      return !!script.value.trim()
    default:
      return true
  }
}

const stepStatus = (key: StepKey): { text: string; tone: string } | null => {
  switch (key) {
    case 'mode':
      return { text: modeLabels[mode.value ?? ''] ?? 'Выбор', tone: TONE.mode }
    case 'video':
      return lesson.value?.video_url
        ? { text: 'Загружено', tone: TONE.done }
        : { text: 'Нет файла', tone: TONE.idle }
    case 'presentation':
      if (analyzing.value) return { text: 'Анализ…', tone: TONE.wait }
      return lesson.value?.pptx_path
        ? { text: 'Готово', tone: TONE.done }
        : { text: 'Нужен файл', tone: TONE.idle }
    case 'script':
      return script.value.trim()
        ? { text: 'Заполнен', tone: TONE.done }
        : { text: 'Пусто', tone: TONE.idle }
    case 'generate':
      if (generating.value) return { text: 'Генерация…', tone: TONE.wait }
      return lesson.value?.video_url
        ? { text: 'Готово', tone: TONE.done }
        : { text: 'Не готово', tone: TONE.idle }
    case 'history':
      return { text: String(videoHistory.value.length), tone: TONE.idle }
  }
}

const STEP_TITLES: Record<StepKey, string> = {
  mode: 'Способ создания',
  video: 'Загрузка видео',
  presentation: 'Презентация',
  script: 'Текст озвучки',
  generate: 'Генерация видео',
  history: 'История генераций',
}

const workflowSteps = computed(() => {
  const keys: StepKey[] = ['mode']
  if (isVideoUpload.value) keys.push('video')
  if (isManual.value || isAuto.value) keys.push('presentation')
  if (isManual.value) keys.push('script')
  if (isManual.value || isAuto.value) keys.push('generate')
  if (videoHistory.value.length) keys.push('history')
  return keys.map((k) => ({ key: k, title: STEP_TITLES[k], status: stepStatus(k) }))
})

const activeStep = ref<StepKey>('mode')

const pickInitialStep = () => {
  const keys = workflowSteps.value.map((s) => s.key as StepKey)
  // Fresh draft (nothing uploaded yet) → open the very first step so the teacher
  // confirms the creation method, instead of jumping ahead to "Презентация".
  const hasProgress =
    !!lesson.value?.pptx_path || !!lesson.value?.video_url || !!script.value.trim()
  if (!hasProgress) {
    activeStep.value = keys[0] ?? 'mode'
    return
  }
  activeStep.value = keys.find((k) => !isStepDone(k)) ?? keys[keys.length - 1] ?? 'mode'
}

let stepAutoPicked = false
// Auto-select the first incomplete step once the lesson finishes loading.
watch(loading, (l) => {
  if (!l && lesson.value && !stepAutoPicked) {
    pickInitialStep()
    stepAutoPicked = true
  }
})

// Keep the active step valid when the mode change rebuilds the step list.
watch(workflowSteps, (steps) => {
  if (!steps.some((s) => s.key === activeStep.value)) {
    activeStep.value = (steps[0]?.key as StepKey) ?? 'mode'
  }
})

// Surface long-running work: jump to its step when it starts.
watch(analyzing, (v) => { if (v) activeStep.value = 'presentation' })
watch(generating, (v) => { if (v) activeStep.value = 'generate' })

// ── Comments (sticky right column on desktop, drawer on mobile) ─────────────────

const commentsOpen = ref(false)
const commentsTotal = computed(() => commentsStore.getState(lessonId.value).total)

// ── Video history ─────────────────────────────────────────────────────────────

interface VideoItem {
  id: string
  video_url: string
  voice: string
  creation_mode: string
  is_published: boolean
  created_at: string
}

const previewVideoUrl = ref<string | null>(null)
const publishingVideoId = ref<string | null>(null)

const modeHistoryLabels: Record<string, string> = {
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

// The pipeline records each run in history (is_published=false) and only sets
// lesson.video_url on explicit publish, so the inline preview shows the newest
// generated video (history is ordered newest-first).
const latestVideo = computed<VideoItem | null>(() => videoHistory.value[0] ?? null)
const latestVideoUrl = computed(
  () => latestVideo.value?.video_url ?? lesson.value?.video_url ?? null,
)

// Publish the just-previewed (latest) generation straight from the player.
const publishLatest = () => { if (latestVideo.value) void publishVideo(latestVideo.value) }

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
  commentsOpen.value = false
  stepAutoPicked = false
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

    <!-- Sticky tab bar — stays reachable while the workflow scrolls -->
    <div
      class="sticky top-16 z-20 -mx-6 lg:-mx-10 px-6 lg:px-10 pt-1 bg-gray-50/95 backdrop-blur-sm"
    >
      <UiTabs
        :model-value="activeTab"
        :tabs="TAB_ITEMS"
        @update:model-value="setTab"
      />
    </div>

    <div class="lg:grid lg:grid-cols-[minmax(0,1fr)_340px] lg:gap-6 lg:items-start">
      <!-- LEFT: active tab content -->
      <div class="min-w-0 space-y-6">
        <!-- Урок tab — step wizard; panels stay mounted via v-show -->
        <div
          v-show="activeTab === 'lesson'"
          id="tabpanel-lesson"
          role="tabpanel"
          aria-labelledby="tab-lesson"
          class="space-y-6"
        >
          <!-- Mobile step chips (desktop uses the right-column nav) -->
          <LessonWorkflowNav
            v-model="activeStep"
            :steps="workflowSteps"
            orientation="horizontal"
            class="lg:hidden"
          />

          <div v-show="activeStep === 'mode'">
            <section class="bg-white rounded-2xl border border-gray-100 p-6 shadow-soft">
              <CreationModeChooser :model-value="mode" @update:model-value="onModeSelect" />
            </section>
          </div>

          <div v-show="activeStep === 'video'">
            <LessonVideoUploadSection
              v-if="isVideoUpload"
              :video-url="lesson.video_url ?? null"
              :selected-file="videoFile"
              :uploading="uploadingVideo"
              :upload-error="videoUploadError"
              @file-change="videoFile = $event; videoUploadError = ''"
              @upload="uploadVideo"
            />
          </div>

          <div v-show="activeStep === 'presentation'">
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
              :credits-spent="analyzeCreditsSpent"
              :credits-reserved="analyzeCreditsReserved"
              :billed-via="analyzeBilledVia"
              :need-topup="analyzeNeedTopup"
              @file-change="pptxFile = $event; uploadError = ''"
              @upload="uploadPptx"
              @start-analyze="guardedStartAnalysis"
              @cancel-analyze="cancelAnalysis"
              @toggle-slide-editor="showSlideEditor = !showSlideEditor"
              @slide-back="showSlideEditor = false"
              @slide-ready="async () => { showSlideEditor = false; await generateVideo() }"
            />
          </div>

          <div v-show="activeStep === 'script'">
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
          </div>

          <div v-show="activeStep === 'generate'">
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
              :video-url="latestVideoUrl"
              :analyzing="analyzing"
              :has-pptx="!!lesson.pptx_path"
              :is-auto="isAuto"
              :is-manual="isManual"
              :script-is-empty="!script.trim()"
              :credits-spent="creditsSpent"
              :credits-reserved="creditsReserved"
              :billed-via="billedVia"
              :need-topup="needTopup"
              :cancelled="cancelled"
              :latest-published="latestVideo?.is_published ?? false"
              :publishing="!!latestVideo && publishingVideoId === latestVideo.id"
              @generate="generateVideo"
              @cancel="cancelVideo"
              @publish="publishLatest"
              @view-history="activeStep = 'history'"
            />
          </div>

          <div v-show="activeStep === 'history'">
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
                  <span class="text-sm text-gray-500">{{ modeHistoryLabels[video.creation_mode] ?? video.creation_mode }}</span>
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

        <!-- Задания tab panel — v-show keeps the panel's fetched state across switches -->
        <div
          v-show="activeTab === 'assignments'"
          id="tabpanel-assignments"
          role="tabpanel"
          aria-labelledby="tab-assignments"
          class="space-y-6"
        >
          <section class="bg-white rounded-2xl border border-gray-100 p-6 shadow-soft">
            <AssignmentsTeacherPanel :lesson-id="lessonId" />
          </section>
        </div>
      </div>

      <!-- Mobile comments drawer backdrop -->
      <div
        v-if="commentsOpen"
        class="lg:hidden fixed inset-0 z-40 bg-black/40 backdrop-blur-sm"
        @click="commentsOpen = false"
      />

      <!-- RIGHT: sticky step nav (Урок tab) + comments; mobile = comments drawer.
           Single CommentsPanel instance, visible on every tab. -->
      <aside
        class="fixed inset-y-0 right-0 z-50 w-[88%] max-w-sm p-4 bg-gray-50 shadow-2xl flex flex-col transition-transform duration-200
               lg:inset-auto lg:z-auto lg:w-auto lg:max-w-none lg:p-0 lg:bg-transparent lg:shadow-none lg:translate-x-0
               lg:sticky lg:top-16 lg:max-h-[calc(100vh-5rem)]"
        :class="commentsOpen ? 'translate-x-0' : 'translate-x-full lg:translate-x-0'"
      >
        <div class="lg:hidden flex justify-end mb-2 shrink-0">
          <button
            type="button"
            class="p-1.5 rounded-lg text-gray-500 hover:bg-gray-100 transition"
            aria-label="Закрыть комментарии"
            @click="commentsOpen = false"
          >
            <X class="w-5 h-5" />
          </button>
        </div>

        <!-- Desktop-only step navigator -->
        <div
          v-show="activeTab === 'lesson'"
          class="hidden lg:block shrink-0 bg-white rounded-2xl border border-gray-100 shadow-soft p-3 mb-4"
        >
          <div class="px-2 pb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
            Этапы
          </div>
          <LessonWorkflowNav
            v-model="activeStep"
            :steps="workflowSteps"
            orientation="vertical"
          />
        </div>

        <CommentsPanel
          :lesson-id="lessonId"
          :can-delete="canDeleteComment"
          class="flex-1 min-h-0"
        />
      </aside>

      <!-- Mobile comments trigger (FAB) with count badge -->
      <button
        type="button"
        class="lg:hidden fixed bottom-5 right-5 z-30 inline-flex items-center gap-2 rounded-full bg-violet-600 text-white pl-4 pr-5 py-3 shadow-lg hover:bg-violet-700 transition"
        @click="commentsOpen = true"
      >
        <MessageSquare class="w-5 h-5" />
        <span class="text-sm font-medium">Комментарии</span>
        <span
          v-if="commentsTotal"
          class="inline-flex items-center justify-center min-w-5 h-5 px-1.5 rounded-full bg-white/25 text-xs font-semibold"
        >
          {{ commentsTotal }}
        </span>
      </button>
    </div>

    <GenerationCostModal
      :open="costModalOpen"
      :kind="costModalKind"
      :estimate="estimateData"
      :loading="estimateLoading"
      @confirm="onCostConfirm"
      @close="onCostClose"
    />
  </div>
</template>
