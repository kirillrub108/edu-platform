import { CreationMode, type CreationModeValue } from '~/composables/useCreationMode'

export function useLessonData(lessonId: Readonly<Ref<string>>) {
  const { apiFetch } = useApi()

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
    try {
      const form = new FormData()
      form.append('file', pptxFile.value)
      form.append('lesson_id', lessonId.value)
      const result = await apiFetch<any>(`/uploads/pptx?lesson_id=${lessonId.value}`, {
        method: 'POST',
        body: form,
      })
      lesson.value = { ...lesson.value, pptx_path: result.file_path }
      pptxFile.value = null
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
    isAuto, isManual, isVideoUpload,
    load, onModeSelect, uploadPptx, uploadScriptFile, uploadVideo, flushScript,
  }
}
