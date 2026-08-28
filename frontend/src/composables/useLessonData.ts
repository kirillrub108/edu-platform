import { CreationMode, type CreationModeValue } from '~/composables/useCreationMode'
import { DEFAULT_DETAIL_LEVEL, type DetailLevelValue } from '~/composables/useLessonDuration'

export function useLessonData(lessonId: Readonly<Ref<string>>) {
  const { apiFetch } = useApi()
  const { reachGoalOnce } = useMetrika()

  const lesson = ref<any>(null)
  const loading = ref(true)
  const error = ref('')
  const mode = ref<CreationModeValue | null>(null)

  const script = ref('')
  const scriptSaveStatus = ref<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const isDirty = ref(false)
  let scriptDebounceTimer: ReturnType<typeof setTimeout> | null = null
  let programmaticUpdate = false

  const saveScript = async () => {
    if (!isDirty.value) return
    scriptSaveStatus.value = 'saving'
    try {
      await apiFetch(`/lessons/${lessonId.value}/script`, {
        method: 'PUT',
        body: { script: script.value },
      })
      isDirty.value = false
      scriptSaveStatus.value = 'saved'
    } catch {
      scriptSaveStatus.value = 'error'
    }
  }

  // Prevents the watch from treating programmatic script.value assignments as user edits.
  const setProgrammaticScript = (value: string) => {
    programmaticUpdate = true
    script.value = value
    programmaticUpdate = false
  }

  watch(script, () => {
    if (programmaticUpdate) return
    isDirty.value = true
    scriptSaveStatus.value = 'idle'
    if (scriptDebounceTimer) clearTimeout(scriptDebounceTimer)
    scriptDebounceTimer = setTimeout(saveScript, 500)
  }, { flush: 'sync' })

  const pptxFile = ref<File | null>(null)
  const uploading = ref(false)
  const uploadError = ref('')

  const scriptFile = ref<File | null>(null)
  const uploadingScript = ref(false)
  const scriptUploadError = ref('')

  const videoFile = ref<File | null>(null)
  const uploadingVideo = ref(false)
  const videoUploadError = ref('')

  const load = async () => {
    loading.value = true
    error.value = ''
    try {
      const data = await apiFetch<any>(`/lessons/${lessonId.value}`)
      lesson.value = data
      setProgrammaticScript(data.script ?? data.text_content ?? '')
      detailLevel.value = data.detail_level ?? DEFAULT_DETAIL_LEVEL
      isDirty.value = false
      if (data.creation_mode) {
        mode.value = data.creation_mode as CreationModeValue
      }
      // Safety: analyzing/ready_for_edit status implies auto mode regardless of stored creation_mode.
      if (data.status === 'analyzing' || data.status === 'ready_for_edit') {
        mode.value = CreationMode.PRESENTATION_AUTO
      }
    } catch (e: any) {
      error.value = e?.data?.detail ?? 'Не удалось загрузить урок'
    } finally {
      loading.value = false
    }
    void loadSlideCount()
  }

  // How deeply the narration covers each slide; the lesson's length follows.
  const detailLevel = ref<DetailLevelValue>(DEFAULT_DETAIL_LEVEL)
  const detailLevelError = ref('')

  const setDetailLevel = async (value: DetailLevelValue) => {
    const previous = detailLevel.value
    detailLevel.value = value
    detailLevelError.value = ''
    try {
      await apiFetch(`/lessons/${lessonId.value}`, {
        method: 'PUT',
        body: { detail_level: value },
      })
      lesson.value = { ...lesson.value, detail_level: value }
    } catch (e: any) {
      detailLevel.value = previous
      detailLevelError.value = e?.data?.detail ?? 'Не удалось сохранить степень раскрытия'
    }
  }

  // Slide count drives the duration estimate shown next to the choice. It comes
  // from the estimate endpoint (which reads it off the PPTX) because the deck is
  // not analysed yet at the point the teacher makes this choice.
  const slideCount = ref(0)

  const loadSlideCount = async () => {
    if (!lesson.value?.pptx_path) return
    try {
      const est = await apiFetch<any>(`/lessons/${lessonId.value}/generation-estimate`)
      slideCount.value = est?.video?.slides ?? 0
    } catch {
      slideCount.value = 0  // estimate is a nicety — never block the page on it
    }
  }

  const onModeSelect = async (m: CreationModeValue) => {
    mode.value = m
    try {
      await apiFetch(`/lessons/${lessonId.value}`, { method: 'PUT', body: { creation_mode: m } })
    } catch { /* visual selection still works */ }
  }

  const uploadPptx = async () => {
    if (!pptxFile.value) return
    uploading.value = true
    uploadError.value = ''
    const fileSizeMb = pptxFile.value.size / (1024 * 1024)
    try {
      const form = new FormData()
      form.append('file', pptxFile.value)
      form.append('lesson_id', lessonId.value)
      const result = await apiFetch<any>(`/uploads/pptx?lesson_id=${lessonId.value}`, {
        method: 'POST',
        body: form,
      })
      lesson.value = { ...lesson.value, pptx_path: result.file_path }
      // reachGoalOnce keyed by lessonId — a teacher replacing the deck later
      // in the same lesson must not recount the goal.
      reachGoalOnce(METRIKA_GOALS.pptxUpload, lessonId.value, {
        lesson_id: lessonId.value,
        size_mb: Math.round(fileSizeMb * 100) / 100,
      })
      pptxFile.value = null
      void loadSlideCount()
    } catch (e: any) {
      uploadError.value = e?.data?.detail ?? 'Ошибка загрузки'
    } finally {
      uploading.value = false
    }
  }

  const uploadScriptFile = async () => {
    if (!scriptFile.value) return
    uploadingScript.value = true
    scriptUploadError.value = ''
    try {
      const form = new FormData()
      form.append('file', scriptFile.value)
      const result = await apiFetch<any>(`/uploads/script?lesson_id=${lessonId.value}`, {
        method: 'POST',
        body: form,
      })
      setProgrammaticScript(result.script ?? '')
      isDirty.value = true  // uploaded text should be auto-saved
      scriptFile.value = null
    } catch (e: any) {
      scriptUploadError.value = e?.data?.detail ?? 'Не удалось обработать файл'
    } finally {
      uploadingScript.value = false
    }
  }

  const uploadVideo = async () => {
    if (!videoFile.value) return
    uploadingVideo.value = true
    videoUploadError.value = ''
    try {
      const form = new FormData()
      form.append('file', videoFile.value)
      const updated = await apiFetch<any>(`/lessons/${lessonId.value}/upload-video`, {
        method: 'POST',
        body: form,
      })
      lesson.value = updated
      videoFile.value = null
    } catch (e: any) {
      videoUploadError.value = e?.data?.detail ?? 'Не удалось загрузить видео'
    } finally {
      uploadingVideo.value = false
    }
  }

  // Clears the pending debounce, marks dirty, and saves — used by video generation
  // to flush any in-flight script edits before starting the pipeline.
  const flushScript = async () => {
    if (scriptDebounceTimer) {
      clearTimeout(scriptDebounceTimer)
      scriptDebounceTimer = null
    }
    isDirty.value = true
    await saveScript()
  }

  onUnmounted(() => {
    if (scriptDebounceTimer) {
      clearTimeout(scriptDebounceTimer)
      scriptDebounceTimer = null
    }
    // Fire-and-forget: await is not allowed in onUnmounted.
    if (isDirty.value) void saveScript()
  })

  const isAuto = computed(() => mode.value === CreationMode.PRESENTATION_AUTO)
  const isManual = computed(() => mode.value === CreationMode.PRESENTATION_AND_TEXT)
  const isVideoUpload = computed(() => mode.value === CreationMode.VIDEO_UPLOAD)

  return {
    lesson, loading, error, mode,
    script, scriptSaveStatus,
    pptxFile, uploading, uploadError,
    scriptFile, uploadingScript, scriptUploadError,
    videoFile, uploadingVideo, videoUploadError,
    detailLevel, detailLevelError, setDetailLevel,
    slideCount, loadSlideCount,
    isAuto, isManual, isVideoUpload,
    load, onModeSelect, uploadPptx, uploadScriptFile, uploadVideo, flushScript,
  }
}
