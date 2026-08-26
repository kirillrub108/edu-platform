/** One progress frame from `/lessons/{id}/progress-stream`. */
export interface ProgressStreamEvent {
  step?: string
  done?: number
  total?: number
  status?: string
  credits_spent?: number
  video_url?: string | null
}

// Backoff for reconnecting after the browser gives up on its own.
//
// EventSource already retries a dropped connection by itself (using the
// server's `retry:` hint) and only gives up permanently when a reconnect gets a
// non-2xx response. That is exactly what a blue-green deploy can produce for a
// moment while the upstream switches, and without these retries a single
// badly-timed reconnect would drop the page to interval polling for the rest of
// the generation. Total ≈ 15 s, after which onClose hands over to the fallback.
const RECONNECT_DELAYS_MS: readonly number[] = [1000, 2000, 4000, 8000]

export function useProgressStream(
  lessonId: Readonly<Ref<string>>,
  onEvent: (data: ProgressStreamEvent) => void,
  onClose?: () => void,
) {
  const config = useRuntimeConfig()
  const base = config.public.apiBase as string
  const isConnected = ref(false)

  let es: EventSource | null = null
  let retryTimer: ReturnType<typeof setTimeout> | null = null
  let attempt = 0
  let stopped = true

  const clearRetry = () => {
    if (retryTimer !== null) {
      clearTimeout(retryTimer)
      retryTimer = null
    }
  }

  const stop = () => {
    stopped = true
    clearRetry()
    attempt = 0
    es?.close()
    es = null
    isConnected.value = false
  }

  const scheduleReconnect = () => {
    if (stopped) return
    const delay = RECONNECT_DELAYS_MS[attempt]
    if (delay === undefined) {
      // Out of attempts — let the caller fall back to polling.
      onClose?.()
      return
    }
    attempt += 1
    retryTimer = setTimeout(() => {
      retryTimer = null
      if (!stopped) open()
    }, delay)
  }

  const open = () => {
    const url = `${base}/lessons/${lessonId.value}/progress-stream`
    // withCredentials sends the httpOnly access_token cookie cross-origin.
    // Works because CORS is configured with explicit origins + allow_credentials=True.
    const source = new EventSource(url, { withCredentials: true })
    es = source

    source.onopen = () => {
      isConnected.value = true
      attempt = 0
    }

    source.onmessage = (event) => {
      try {
        onEvent(JSON.parse(event.data) as ProgressStreamEvent)
      } catch { /* ignore malformed messages */ }
    }

    source.onerror = () => {
      // A later start()/stop() already replaced this stream — ignore its noise.
      if (es !== source) return
      isConnected.value = false
      // CONNECTING means the browser is retrying on its own; only CLOSED is
      // final and ours to handle.
      if (source.readyState !== EventSource.CLOSED) return
      source.close()
      es = null
      scheduleReconnect()
    }
  }

  const start = () => {
    if (typeof EventSource === 'undefined') return
    stop()
    stopped = false
    open()
  }

  return { start, stop, isConnected }
}
