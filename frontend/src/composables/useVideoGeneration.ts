import { CreationMode, type CreationModeValue } from '~/composables/useCreationMode'
import { friendlyApiError, friendlyTaskError } from '~/composables/useBillingMeta'

export function useVideoGeneration(
  lessonId: Readonly<Ref<string>>,
  lesson: Ref<any>,
  mode: Readonly<Ref<CreationModeValue | null>>,
  script: Readonly<Ref<string>>,
  flushScript: () => Promise<void>,
  isAuto: Readonly<Ref<boolean>>,
  showSlideEditor: Ref<boolean>,
) {
  const { apiFetch } = useApi()
  const billing = useBillingStore()

  // Голоса openai/tts-1 (значения уходят на бэкенд как есть).
  const voices: Array<{ value: string; label: string }> = [
    { value: 'nova',    label: 'Nova (жен.)' },
    { value: 'shimmer', label: 'Shimmer (жен., мягкий)' },
    { value: 'coral',   label: 'Coral (жен.)' },
    { value: 'sage',    label: 'Sage (жен., спокойный)' },
    { value: 'alloy',   label: 'Alloy (нейтральный)' },
    { value: 'onyx',    label: 'Onyx (муж., низкий)' },
    { value: 'echo',    label: 'Echo (муж.)' },
    { value: 'fable',   label: 'Fable (муж., выразительный)' },
    { value: 'ash',     label: 'Ash (муж.)' },
  ]

  const selectedVoice = ref<string>('nova')
  const taskId = ref<string | null>(null)
  const taskStatus = ref('')
  const taskMeta = ref<{ step: string; done: number; total: number } | null>(null)
  const taskError = ref('')
  const generating = ref(false)
  const cancellingVideo = ref(false)
  const pipelineDone = ref(false)

  // Billing telemetry from progress events / start response.
  const creditsSpent = ref(0)
  const creditsReserved = ref(0)
  const billedVia = ref<string | null>(null)
  // 402 from generate-video → show a "пополнить баланс" CTA.
  const needTopup = ref(false)
  // Short-lived banner "Генерация отменена, списано N CR".
  const cancelled = ref(false)
  let cancelledTimer: ReturnType<typeof setTimeout> | null = null

  let pollTimer: ReturnType<typeof setInterval> | null = null
  let statusPollTimer: ReturnType<typeof setInterval> | null = null
  // One-shot guard: refresh the balance once the task starts reporting progress,
  // which is when the credit RESERVE has landed.
  let reserveReflected = false

  const stopPollTimer = () => {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
  }
  const stopStatusPollTimer = () => {
    if (statusPollTimer) { clearInterval(statusPollTimer); statusPollTimer = null }
  }

  const applyCredits = (src: any) => {
    if (!src) return
    if (src.credits_spent !== undefined) creditsSpent.value = src.credits_spent
    if (src.credits_reserved !== undefined) creditsReserved.value = src.credits_reserved
    if (src.billed_via !== undefined) billedVia.value = src.billed_via
  }

  // Terminal "cancelled": stop tracking, reflect the partial charge, reload the
  // lesson — like the error path, but without an error message.
  const onCancelledTerminal = (spent?: number) => {
    stopPolling()
    generating.value = false
    cancellingVideo.value = false
    taskStatus.value = ''
    taskMeta.value = null
    taskError.value = ''
    if (spent !== undefined) creditsSpent.value = spent
    cancelled.value = true
    if (cancelledTimer) clearTimeout(cancelledTimer)
    cancelledTimer = setTimeout(() => { cancelled.value = false }, 60_000)
    apiFetch<any>(`/lessons/${lessonId.value}`).then(d => { lesson.value = d })
    void billing.refresh()
  }

  // SSE stream for real-time progress. Falls back to polling if EventSource
  // is unavailable or the SSE connection closes unexpectedly.
  const progressStream = useProgressStream(lessonId, (data: any) => {
    if (data.step !== undefined) {
      taskMeta.value = { step: data.step, done: data.done ?? 0, total: data.total ?? 1 }
      taskStatus.value = 'PROGRESS'
      applyCredits(data)
      if (!reserveReflected) { reserveReflected = true; void billing.fetchBalance() }
    } else if (data.status === 'cancelled') {
      onCancelledTerminal(data.credits_spent)
    } else if (data.status === 'published') {
      progressStream.stop()
      generating.value = false
      apiFetch<any>(`/lessons/${lessonId.value}`).then(d => {
        lesson.value = d
        if (d.status === 'error') {
          taskError.value = friendlyTaskError(d.last_warning) ?? 'Ошибка генерации видео.'
        } else {
          pipelineDone.value = true
        }
      })
      void billing.refresh()
    } else if (data.status === 'error') {
      progressStream.stop()
      generating.value = false
      apiFetch<any>(`/lessons/${lessonId.value}`).then(d => {
        lesson.value = d
        taskError.value = friendlyTaskError(d.last_warning) ?? 'Ошибка генерации видео.'
      })
      void billing.refresh()
    }
  }, () => {
    // SSE closed unexpectedly — fall back to interval polling.
    if (!generating.value) return
    if (taskId.value) {
      taskStatus.value = 'PENDING'
      pollTimer = setInterval(pollStatus, 3000)
    } else {
      statusPollTimer = setInterval(pollForVideoCompletion, 3000)
    }
  })

  const stopPolling = () => { stopPollTimer(); stopStatusPollTimer(); progressStream.stop() }

  // Fallback path: no task_id — poll the lesson status directly.
  const pollForVideoCompletion = async () => {
    try {
      const data = await apiFetch<any>(`/lessons/${lessonId.value}`)
      if (data.status !== 'processing') {
        stopStatusPollTimer()
        generating.value = false
        lesson.value = data
        if (data.status === 'error') {
          taskError.value = friendlyTaskError(data.last_warning) ?? 'Ошибка генерации видео.'
        } else if (data.status === 'cancelled') {
          cancellingVideo.value = false
          cancelled.value = true
          if (cancelledTimer) clearTimeout(cancelledTimer)
          cancelledTimer = setTimeout(() => { cancelled.value = false }, 60_000)
        } else {
          pipelineDone.value = true
        }
        void billing.refresh()
      }
    } catch { /* network glitch — keep polling */ }
  }

  // Primary path: Celery task_id available — poll the task status endpoint.
  const pollStatus = async () => {
    if (!taskId.value) return
    try {
      const res = await apiFetch<any>(`/lessons/${lessonId.value}/task-status/${taskId.value}`)
      taskStatus.value = res.status
      if (res.status === 'PROGRESS' && res.meta) {
        taskMeta.value = res.meta
        applyCredits(res.meta)
      }
      if (res.status === 'REVOKED') {
        // Lesson status 'cancelled' is mapped to celery REVOKED by the backend.
        onCancelledTerminal(res.meta?.credits_spent)
      } else if (res.status === 'SUCCESS') {
        stopPollTimer()
        generating.value = false
        const data = await apiFetch<any>(`/lessons/${lessonId.value}`)
        lesson.value = data
        // The task returns normally even when it bails on insufficient credits
        // (lesson.status=error + last_warning), so surface that here.
        if (data.status === 'error') {
          taskError.value = friendlyTaskError(data.last_warning) ?? 'Ошибка генерации видео.'
        } else {
          pipelineDone.value = true
        }
        void billing.refresh()
      } else if (res.status === 'FAILURE') {
        stopPollTimer()
        generating.value = false
        taskError.value = friendlyTaskError(res.result?.error) ?? 'Неизвестная ошибка'
        void billing.refresh()
      }
    } catch { /* network glitch — keep polling */ }
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
    pipelineDone.value = false
    generating.value = true
    reserveReflected = false
    needTopup.value = false
    cancelled.value = false
    if (cancelledTimer) { clearTimeout(cancelledTimer); cancelledTimer = null }
    creditsSpent.value = 0
    creditsReserved.value = 0
    billedVia.value = null
    stopPolling()
    if (mode.value === CreationMode.PRESENTATION_AND_TEXT) {
      await flushScript()
    }
    try {
      const res = await apiFetch<any>(`/lessons/${lessonId.value}/generate-video`, {
        method: 'POST',
        body: { voice: selectedVoice.value },
      })
      taskId.value = res.task_id
      taskStatus.value = 'PENDING'
      if (res.credit_estimate !== undefined) creditsReserved.value = res.credit_estimate
      if (res.billed_via !== undefined) billedVia.value = res.billed_via
      if (typeof EventSource !== 'undefined') {
        progressStream.start()
      } else {
        pollTimer = setInterval(pollStatus, 3000)
      }
    } catch (e: any) {
      generating.value = false
      const msg = friendlyApiError(e)
      taskError.value = msg.message
      needTopup.value = msg.insufficient
    }
  }

  const cancelVideo = async () => {
    cancellingVideo.value = true
    let cooperative = false
    try {
      const res = await apiFetch<any>(`/lessons/${lessonId.value}/cancel-generation`, {
        method: 'POST',
      })
      // Cooperative: the pipeline stops itself at the next slide — keep the
      // "cancelling" state and wait for the terminal SSE {"status":"cancelled"}.
      cooperative = res?.mode === 'cooperative'
      if (cooperative) return
      // Immediate (or nothing to cancel): status already rolled back server-side.
      stopPolling()
      generating.value = false
      taskStatus.value = ''
      taskMeta.value = null
      taskError.value = ''
      const savedScrollY = window.scrollY
      const data = await apiFetch<any>(`/lessons/${lessonId.value}`)
      lesson.value = data
      await nextTick()
      window.scrollTo({ top: savedScrollY, behavior: 'instant' })
      // Always show slide editor after cancel in auto mode — task may have finished
      // just before cancel committed, so lesson status could be 'published' rather
      // than 'ready_for_edit', and the watch wouldn't open the editor automatically.
      if (isAuto.value) showSlideEditor.value = true
      void billing.refresh()
    } catch { /* ignore */ } finally {
      if (!cooperative) cancellingVideo.value = false
    }
  }

  // Restore-flow: if lesson is already processing when the page mounts, resume
  // tracking the in-progress video job after a page refresh.
  watch(lesson, (data) => {
    if (!data || generating.value) return
    if (data.status === 'processing') {
      generating.value = true
      stopPolling()
      if (typeof EventSource !== 'undefined') {
        taskId.value = data.video_task_id ?? null
        progressStream.start()
      } else if (data.video_task_id) {
        taskId.value = data.video_task_id
        taskStatus.value = 'PENDING'
        pollTimer = setInterval(pollStatus, 2000)
      } else {
        statusPollTimer = setInterval(pollForVideoCompletion, 3000)
      }
    }
  }, { immediate: true })

  onUnmounted(() => {
    stopPolling()
    if (cancelledTimer) { clearTimeout(cancelledTimer); cancelledTimer = null }
  })

  const stages = computed(() => {
    const base = [
      { key: 'slides',   label: 'Слайды' },
      { key: 'summary',  label: 'Саммари' },
      { key: 'llm',      label: 'Текст' },
      { key: 'tts',      label: 'Озвучка' },
      { key: 'encoding', label: 'Видео' },
    ]
    // Vision/auto mode skips the summary stage — per-slide texts are already in the DB.
    return mode.value === CreationMode.PRESENTATION_AUTO
      ? base.filter(s => s.key !== 'summary')
      : base
  })

  const currentStageIdx = computed(() => {
    if (pipelineDone.value) return stages.value.length
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

  const showPipeline = computed(() =>
    generating.value || taskStatus.value === 'PROGRESS' || lesson.value?.status === 'processing',
  )

  const canGenerateVideo = computed(() => {
    if (!lesson.value?.pptx_path) return false
    if (generating.value || lesson.value.status === 'processing') return false
    if (isAuto.value) {
      // 'cancelled' allows a restart, same as draft/ready_for_edit.
      return ['ready_for_edit', 'published', 'cancelled'].includes(lesson.value.status)
    }
    if (mode.value === CreationMode.PRESENTATION_AND_TEXT) {
      return script.value.trim().length > 0
    }
    return false
  })

  return {
    voices, selectedVoice,
    generating, cancellingVideo, taskError,
    creditsSpent, creditsReserved, billedVia, needTopup, cancelled,
    generateVideo, cancelVideo, stopPolling,
    showPipeline, pipelineStages, currentStageIdx, canGenerateVideo,
  }
}
