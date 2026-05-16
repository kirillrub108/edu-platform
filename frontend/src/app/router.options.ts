import type { RouterConfig } from '@nuxt/schema'

const EXCLUDED_PATHS = ['/login', '/register']

// Tracks whether this is the very first scrollBehavior call after the
// document loaded. The PerformanceNavigationTiming API only describes the
// page-load navigation, so we can only consult it on that first call.
let isFirstScrollBehaviorCall = true

declare global {
  interface Window {
    /** Hand-off slot for scroll-restoration.client.ts: { fullPath, targetY } */
    __scrollToRestore?: { path: string; y: number }
  }
}

function getInitialNavigationType(): string | null {
  if (typeof performance === 'undefined' || !performance.getEntriesByType) return null
  try {
    const entries = performance.getEntriesByType('navigation') as PerformanceNavigationTiming[]
    return entries[0]?.type ?? null
  } catch {
    return null
  }
}

export default <RouterConfig>{
  scrollBehavior(to, _from, savedPosition) {
    const wasFirstCall = isFirstScrollBehaviorCall
    isFirstScrollBehaviorCall = false

    if (to.hash) return { el: to.hash, top: 80, behavior: 'smooth' }
    if (EXCLUDED_PATHS.includes(to.path)) return { top: 0, left: 0 }
    if (typeof sessionStorage === 'undefined') return { top: 0, left: 0 }

    // --- "Restore or fresh?" detection ---
    //
    // For the initial page-load navigation:
    //   1. PerformanceNavigationTiming type ('reload' / 'back_forward')
    //   2. sessionStorage flag set in beforeunload/pagehide (backup)
    //
    // For subsequent SPA navigations:
    //   savedPosition  — non-null only for popstate (back/forward inside the SPA)
    let shouldRestore: boolean
    if (wasFirstCall) {
      const navType = getInitialNavigationType()
      if (navType === 'reload' || navType === 'back_forward') {
        shouldRestore = true
      } else if (navType === 'navigate' || navType === 'prerender') {
        shouldRestore = false
      } else {
        // Performance API not available — fall back to the flag.
        let flagged = false
        try { flagged = sessionStorage.getItem('scroll:navigation-type') === 'reload' } catch {}
        shouldRestore = flagged
      }
      try { sessionStorage.removeItem('scroll:navigation-type') } catch {}
    } else {
      shouldRestore = savedPosition != null
    }

    if (shouldRestore) {
      // Hand off the actual scroll work to scroll-restoration.client.ts.
      // We read the saved Y for the exact same `fullPath` and pass both along.
      // We then DELETE the sessionStorage key so the page's restoreScroll()
      // (called in every page's onMounted) finds nothing and short-circuits —
      // this removes any race between two different restoration mechanisms.
      try {
        const raw = sessionStorage.getItem('scroll:' + to.fullPath)
        const y = Number(raw)
        if (raw != null && Number.isFinite(y) && y > 0) {
          window.__scrollToRestore = { path: to.fullPath, y }
          sessionStorage.removeItem('scroll:' + to.fullPath)
        }
      } catch { /* private mode */ }
      return false
    }

    // Fresh navigation — clear stale Y for the destination so restoreScroll()
    // in onMounted doesn't snap us back to where we were last time.
    try { sessionStorage.removeItem('scroll:' + to.fullPath) } catch {}
    return { top: 0, left: 0 }
  },
}
