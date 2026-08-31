import { onMounted, onUnmounted } from 'vue'

/**
 * Re-runs `refetch` when the user returns to the tab, so a list that changed
 * server-side while they were away — a teacher granting course access, say —
 * shows up without a manual reload.
 *
 * Deliberately not a poll or a socket: the student is almost never staring at
 * an idle dashboard at the exact moment access is granted, so the cheap
 * trigger covers the real case. Throttled, because an alt-tab flurry fires
 * both `focus` and `visibilitychange`.
 */
export function useRefetchOnFocus(refetch: () => unknown, minIntervalMs = 5000): void {
  let lastRun = 0

  const run = (): void => {
    if (document.visibilityState !== 'visible') return
    const now = Date.now()
    if (now - lastRun < minIntervalMs) return
    lastRun = now
    void refetch()
  }

  onMounted(() => {
    lastRun = Date.now()
    document.addEventListener('visibilitychange', run)
    window.addEventListener('focus', run)
  })

  onUnmounted(() => {
    document.removeEventListener('visibilitychange', run)
    window.removeEventListener('focus', run)
  })
}
