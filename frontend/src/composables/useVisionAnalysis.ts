import { friendlyApiError, friendlyTaskError } from '~/composables/useBillingMeta'

interface SnapshotPanel {
  takeSnapshot(): void
  clearSnapshot(): void
  restoreFromSnapshot(): void
}

export function useVisionAnalysis(
  lessonId: Readonly<Ref<string>>,
  lesson: Ref<any>,
  panelRef: Readonly<Ref<SnapshotPanel | null>>,
  showSlideEditor: Ref<boolean>,
) {
  const { apiFetch } = useApi()
  const billing = useBillingStore()

  const analyzeTaskId = ref<string | null>(null)
  const analyzeStatus = ref('')
  const analyzeMeta = ref<{ step?: string; done?: number; total?: number } | null>(null)
  const analyzeError = ref('')
  const analyzing = ref(false)
  const cancellingAnalysis = ref(false)

  // Billing telemetry from progress events / start response.
  const creditsSpent = ref(0)
  const creditsReserved = ref(0)
  const billedVia = ref<string | null>(null)
  // 402 from /analyze → show a "пополнить баланс" CTA.
  const needTopup = ref(false)

  let analyzeTimer: ReturnType<typeof setInterval> | null = null
  let statusPollTimer: ReturnType<typeof setInterval> | null = null
  // One-shot guard: refresh the balance once analysis starts reporting progress,
  // which is when the credit RESERVE has landed.
  let reserveReflected = false

  const stopAnalyzePolling = () => {
    if (analyzeTimer) { clearInterval(analyzeTimer); analyzeTimer = null }
  }
  const stopStatusPolling = () => {
    if (statusPollTimer) { clearInterval(statusPollTimer); statusPollTimer = null }
  }

  const applyCredits = (src: any) => {
    if (!src) return
    if (src.credits_spent !== undefined) creditsSpent.value = src.credits_spent
    if (src.credits_reserved !== undefined) creditsReserved.value = src.credits_reserved
    if (src.billed_via !== undefined) billedVia.value = src.billed_via
  }

  // Terminal "cancelled": after a cooperative cancel the lesson status becomes
  // 'cancelled' — update the lesson locally and roll the editor back.
  const onCancelledTerminal = (spent?: number) => {
    stopPolling()
    analyzing.value = false
    cancellingAnalysis.value = false
    analyzeTaskId.value = null
    analyzeStatus.value = ''
    analyzeMeta.value = null
    analyzeError.value = ''
    if (spent !== undefined) creditsSpent.value = spent
    lesson.value = { ...lesson.value, status: 'cancelled', analyze_task_id: null }
    panelRef.value?.restoreFromSnapshot()
    void billing.refresh()
  }

  // SSE stream for real-time progress. Falls back to polling if EventSource
  // is unavailable or the SSE connection closes unexpectedly.
  const progressStream = useProgressStream(lessonId, (data: any) => {
    if (data.step !== undefined) {
      analyzeMeta.value = { step: data.step, done: data.done, total: data.total }
      analyzeStatus.value = 'PROGRESS'
      applyCredits(data)
      if (!reserveReflected) { reserveReflected = true; void billing.fetchBalance() }
    } else if (data.status === 'cancelled') {
      onCancelledTerminal(data.credits_spent)
    } else if (data.status === 'ready_for_edit') {
      progressStream.stop()
      analyzing.value = false
      analyzeStatus.value = 'SUCCESS'
      panelRef.value?.clearSnapshot()
      apiFetch<any>(`/lessons/${lessonId.value}`).then(d => {
        lesson.value = d
        showSlideEditor.value = true
      })
      void billing.refresh()
    } else if (data.status === 'error') {
      progressStream.stop()
      analyzing.value = false
      analyzeError.value = 'Ошибка анализа. Попробуйте запустить снова.'
      panelRef.value?.restoreFromSnapshot()
      void billing.refresh()
    }
  }, () => {
    // SSE closed unexpectedly — fall back to interval polling.
    if (!analyzing.value) return
    if (analyzeTaskId.value) {
      analyzeStatus.value = 'PENDING'
      analyzeTimer = setInterval(pollAnalyzeStatus, 2000)
    } else {
      statusPollTimer = setInterval(pollForAnalysisCompletion, 2000)
    }
  })

  const stopPolling = () => { stopAnalyzePolling(); stopStatusPolling(); progressStream.stop() }

  // Fallback path: no task_id — poll the lesson status directly.
  const pollForAnalysisCompletion = async () => {
    try {
      const data = await apiFetch<any>(`/lessons/${lessonId.value}`)
      if (data.status !== 'analyzing') {
        stopStatusPolling()
        analyzing.value = false
        lesson.value = data
        if (data.status === 'ready_for_edit') {
          showSlideEditor.value = true
        } else if (data.status === 'cancelled') {
          cancellingAnalysis.value = false
          panelRef.value?.restoreFromSnapshot()
        } else if (data.status === 'error') {
          analyzeError.value =
            friendlyTaskError(data.last_warning) ?? 'Ошибка анализа. Попробуйте запустить снова.'
        }
        void billing.refresh()
      }
    } catch { /* network glitch — keep polling */ }
  }

  // Primary path: Celery task_id available — poll the task status endpoint.
  const pollAnalyzeStatus = async () => {
    if (!analyzeTaskId.value) return
    try {
      const res = await apiFetch<any>(
        `/lessons/${lessonId.value}/analysis-status/${analyzeTaskId.value}`,
      )
      analyzeStatus.value = res.status
      if (res.status === 'PROGRESS') {
        analyzeMeta.value = { step: res.step, done: res.done, total: res.total }
        applyCredits(res.meta ?? res)
      }
      if (res.status === 'REVOKED') {
        // Lesson status 'cancelled' is mapped to celery REVOKED by the backend.
        onCancelledTerminal(res.meta?.credits_spent ?? res.credits_spent)
      } else if (res.status === 'SUCCESS') {
        stopPolling()
        analyzing.value = false
        panelRef.value?.clearSnapshot()
        const data = await apiFetch<any>(`/lessons/${lessonId.value}`)
        lesson.value = data
        showSlideEditor.value = true
        void billing.refresh()
      } else if (res.status === 'FAILURE' || res.error) {
        stopPolling()
        analyzing.value = false
        analyzeError.value = friendlyTaskError(res.error) ?? 'Ошибка анализа'
        panelRef.value?.restoreFromSnapshot()
        void billing.refresh()
      }
    } catch { /* network glitch — keep polling */ }
  }

  const startAnalysis = async () => {
    if (!lesson.value?.pptx_path) {
      analyzeError.value = 'Сначала загрузите презентацию'
      return
    }
    if (showSlideEditor.value) panelRef.value?.takeSnapshot()
    analyzeError.value = ''
    analyzeMeta.value = null
    analyzing.value = true
    reserveReflected = false
    needTopup.value = false
    creditsSpent.value = 0
    creditsReserved.value = 0
    billedVia.value = null
    stopPolling()
    try {
      const res = await apiFetch<any>(`/lessons/${lessonId.value}/analyze`, { method: 'POST' })
      analyzeTaskId.value = res.task_id
      analyzeStatus.value = 'PENDING'
      if (res.credit_estimate !== undefined) creditsReserved.value = res.credit_estimate
      if (res.billed_via !== undefined) billedVia.value = res.billed_via
      if (typeof EventSource !== 'undefined') {
        progressStream.start()
      } else {
        analyzeTimer = setInterval(pollAnalyzeStatus, 2000)
      }
    } catch (e: any) {
      analyzing.value = false
      const msg = friendlyApiError(e)
      analyzeError.value = msg.message
      needTopup.value = msg.insufficient
    }
  }

  const cancelAnalysis = async () => {
    cancellingAnalysis.value = true
    let cooperative = false
    try {
      const res = await apiFetch<any>(`/lessons/${lessonId.value}/cancel-generation`, {
        method: 'POST',
      })
      // Cooperative: the task stops itself at the next slide — keep the
      // "cancelling" state and wait for the terminal SSE {"status":"cancelled"}.
      cooperative = res?.mode === 'cooperative'
      if (cooperative) return
      // Immediate (or nothing to cancel): status already rolled back server-side.
      stopPolling()
      analyzing.value = false
      analyzeTaskId.value = null
      analyzeStatus.value = ''
      analyzeMeta.value = null
      lesson.value = { ...lesson.value, status: res?.status ?? 'cancelled', analyze_task_id: null }
      panelRef.value?.restoreFromSnapshot()
      void billing.refresh()
    } catch (e: any) {
      analyzeError.value = e?.data?.detail ?? 'Не удалось отменить анализ'
    } finally {
      if (!cooperative) cancellingAnalysis.value = false
    }
  }

  // Restore-flow: if lesson is already analyzing when the page mounts, resume
  // tracking in-progress work after a page refresh.
  watch(lesson, (data) => {
    if (!data || analyzing.value) return
    if (data.status === 'analyzing') {
      analyzing.value = true
      stopPolling()
      if (typeof EventSource !== 'undefined') {
        analyzeTaskId.value = data.analyze_task_id ?? null
        progressStream.start()
      } else if (data.analyze_task_id) {
        analyzeTaskId.value = data.analyze_task_id
        analyzeStatus.value = 'PENDING'
        analyzeTimer = setInterval(pollAnalyzeStatus, 2000)
      } else {
        statusPollTimer = setInterval(pollForAnalysisCompletion, 2000)
      }
    } else if (data.status === 'ready_for_edit') {
      showSlideEditor.value = true
    }
  }, { immediate: true })

  onUnmounted(stopPolling)

  return {
    analyzing, analyzeStatus, analyzeMeta, analyzeError, cancellingAnalysis,
    creditsSpent, creditsReserved, billedVia, needTopup,
    startAnalysis, cancelAnalysis, stopPolling,
  }
}
