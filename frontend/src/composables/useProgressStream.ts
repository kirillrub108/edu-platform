export function useProgressStream(
  lessonId: Readonly<Ref<string>>,
  onEvent: (data: any) => void,
  onClose?: () => void,
) {
  const config = useRuntimeConfig()
  const base = config.public.apiBase as string
  const isConnected = ref(false)
  let es: EventSource | null = null

  const stop = () => {
    es?.close()
    es = null
    isConnected.value = false
  }

  const start = () => {
    if (typeof EventSource === 'undefined') return
    stop()
    const url = `${base}/lessons/${lessonId.value}/progress-stream`
    // withCredentials sends the httpOnly access_token cookie cross-origin.
    // Works because CORS is configured with explicit origins + allow_credentials=True.
    es = new EventSource(url, { withCredentials: true })
    es.onopen = () => { isConnected.value = true }
    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        onEvent(data)
      } catch { /* ignore malformed messages */ }
    }
    es.onerror = () => {
      isConnected.value = false
      if (es?.readyState === EventSource.CLOSED) {
        es = null
        onClose?.()
      }
    }
  }

  return { start, stop, isConnected }
}
