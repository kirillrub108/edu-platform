import { onMounted, onUnmounted } from 'vue'

/**
 * Subscribes to `/students/courses/stream` and calls `onChange` whenever the
 * teacher grants or revokes access, so the cabinet's course list updates
 * without a reload.
 *
 * Deliberately thinner than `useProgressStream`: EventSource already reconnects
 * on its own using the server's `retry:` hint, and `useRefetchOnFocus` covers
 * the case where it gives up for good. There is nothing to replay on reconnect
 * either — the caller just refetches the list.
 */
export function useCourseAccessStream(onChange: () => void): void {
  const config = useRuntimeConfig()
  let es: EventSource | null = null

  const close = (): void => {
    es?.close()
    es = null
  }

  onMounted(() => {
    const base = config.public.apiBase as string
    // withCredentials sends the httpOnly access_token cookie cross-origin;
    // works because CORS runs with explicit origins + allow_credentials=True.
    es = new EventSource(`${base}/students/courses/stream`, { withCredentials: true })
    es.onmessage = () => onChange()
  })

  onUnmounted(close)
}
