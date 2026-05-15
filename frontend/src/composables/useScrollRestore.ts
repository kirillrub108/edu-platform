const SCROLL_KEY = (path: string) => `scroll:${path}`

// Shared flag: plugin's scroll listener checks this to avoid overwriting the
// saved position with intermediate (clamped) scrollY values while we're
// programmatically retrying scrollTo on a page that's still growing in height.
declare global {
  interface Window { __scrollRestoring?: boolean }
}

export function saveScroll(): void {
  if (typeof window === 'undefined') return
  const route = useRoute()
  try {
    sessionStorage.setItem(SCROLL_KEY(route.fullPath), String(window.scrollY))
  } catch { /* private mode */ }
}

export async function restoreScroll(): Promise<void> {
  if (typeof window === 'undefined') return
  // Use window.location instead of useRoute() — useRoute()/useNuxtApp() may
  // become unreliable after await in async lifecycle hooks (lost Vue instance
  // context). window.location is always available and reflects the actual URL.
  const path = window.location.pathname + window.location.search

  let saved: string | null = null
  try {
    saved = sessionStorage.getItem(SCROLL_KEY(path))
  } catch { return }

  if (!saved) return
  const y = Number(saved)
  if (!Number.isFinite(y) || y <= 0) return

  await nextTick()

  // Retry strategy: child components with their own async data loads (e.g.,
  // SlideTextEditor's loadSlides()) cause the page to grow AFTER the parent's
  // load() resolves. A single scrollTo on a too-short page gets clamped to
  // maxScroll (often 0). Retry with backoff until scroll position matches the
  // target or attempts are exhausted.
  window.__scrollRestoring = true
  try {
    const delays = [0, 80, 200, 500, 1000, 1800]
    for (const delay of delays) {
      if (delay === 0) {
        await new Promise<void>(r => requestAnimationFrame(() => r()))
      } else {
        await new Promise<void>(r => setTimeout(r, delay))
      }
      window.scrollTo({ top: y })
      // Success when within 2px (browser sub-pixel rounding tolerance)
      if (Math.abs(window.scrollY - y) <= 2) return
    }
  } finally {
    // Release suppression after one more debounce window so any in-flight
    // scroll event from the last scrollTo won't accidentally save a stale value
    setTimeout(() => { window.__scrollRestoring = false }, 200)
  }
}

export function useScrollRestore(): void {
  onBeforeRouteLeave(() => saveScroll())
}