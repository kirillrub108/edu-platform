import { CreationMode, type CreationModeValue } from '~/composables/useCreationMode'
import { friendlyTaskError } from '~/composables/useBillingMeta'

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

  const voices: Array<{ value: string; label: string }> = [
    { value: 'xenia',   label: 'Ксения (жен.)' },
    { value: 'baya',    label: 'Байя (жен.)' },
    { value: 'kseniya', label: 'Ксения-2 (жен.)' },
    { value: 'aidar',   label: 'Айдар (муж.)' },
    { value: 'eugene',  label: 'Евгений (муж.)' },
  ]

  const selectedVoice = ref<string>('xenia')
  const taskId = ref<string | null>(null)
  const taskStatus = ref('')
  const taskMeta = ref<{ step: string; done: number; total: number } | null>(null)
  const taskError = ref('')
  const generating = ref(false)
  const cancellingVideo = ref(false)
  const pipelineDone = ref(false)

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

  // SSE stream for real-time progress. Falls back to polling if EventSource
  // is unavailable or the SSE connection closes unexpectedly.
  const progressStream = useProgressStream(lessonId, (data: any) => {
    if (data.step !== undefined) {
      taskMeta.value = { step: data.step, done: data.done ?? 0, total: data.total ?? 1 }
      taskStatus.value = 'PROGRESS'
      if (!reserveReflected) { reserveReflected = true; void billing.fetchBalance() }
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
      }
      if (res.status === 'SUCCESS') {
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
      if (typeof EventSource !== 'undefined') {
        progressStream.start()
      } else {
        pollTimer = setInterval(pollStatus, 3000)
      }
    } catch (e: any) {
      generating.value = false
      taskError.value = e?.data?.detail ?? 'Не удалось запустить генерацию'
    }
  }

  const cancelVideo = async () => {
    cancellingVideo.value = true
    try {
      await apiFetch(`/lessons/${lessonId.value}/cancel-video`, { method: 'POST' })
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
    } catch { /* ignore */ } finally {
      cancellingVideo.value = false
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

  onUnmounted(stopPolling)

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
      return lesson.value.status === 'ready_for_edit' || lesson.value.status === 'published'
    }
    if (mode.value === CreationMode.PRESENTATION_AND_TEXT) {
      return script.value.trim().length > 0
    }
    return false
  })

  return {
    voices, selectedVoice,
    generating, cancellingVideo, taskError,
    generateVideo, cancelVideo, stopPolling,
    showPipeline, pipelineStages, currentStageIdx, canGenerateVideo,
  }
}
