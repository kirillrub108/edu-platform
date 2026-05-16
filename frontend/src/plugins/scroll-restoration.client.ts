// Owner of the actual scroll-restoration work.
//
// scrollBehavior (in router.options.ts) decides whether a navigation is a
// "restore" or "fresh" scenario; for restore scenarios it stashes the target
// position in window.__scrollToRestore. This plugin picks that up and performs
// the scroll with a retry loop that copes with content loading asynchronously
// after the route has resolved.
//
// IMPORTANT lifecycle note: in Vue Router 4, scrollBehavior is wrapped in
//   nextTick().then(scrollBehavior)  inside handleScroll(),
// while triggerAfterEach runs synchronously right after finalizeNavigation.
// That means router.afterEach fires BEFORE scrollBehavior. We therefore defer
// our handler one nextTick — handleScroll's `.then(scrollBehavior)` is
// registered earlier (during finalizeNavigation) than our deferred callback,
// so when nextTick resolves scrollBehavior runs first and our callback sees
// window.__scrollToRestore already populated.

declare global {
  interface Window {
    __scrollToRestore?: { path: string; y: number }
    /** Set during restoration so scroll-save.client.ts's scroll listener
     *  won't save intermediate (clamped) values back to sessionStorage. */
    __scrollRestoring?: boolean
  }
}

export default defineNuxtPlugin(() => {
  const router = useRouter()

  if ('scrollRestoration' in history) {
    history.scrollRestoration = 'manual'
  }

  // Backup signal for the Performance Navigation API: written on every unload
  // so scrollBehavior on the next page load can fall back to it if the
  // Performance API isn't available.
  const markReload = () => {
    try { sessionStorage.setItem('scroll:navigation-type', 'reload') } catch {}
  }
  window.addEventListener('beforeunload', markReload)
  window.addEventListener('pagehide', markReload)

  router.afterEach((to) => {
    void nextTick().then(() => {
      const target = window.__scrollToRestore
      if (!target || target.path !== to.fullPath) return
      delete window.__scrollToRestore

      const y = target.y
      if (y <= 0) return

      // Async retry loop: child components frequently load their own data after
      // the parent's load() resolves, growing the page height. A single scrollTo
      // on a too-short page clamps to maxScroll; we keep retrying with longer
      // delays until the scroll lands within 2px of the target.
      void (async () => {
        window.__scrollRestoring = true
        try {
          const delays = [0, 80, 200, 500, 1000, 1800, 2500]
          for (const delay of delays) {
            if (delay === 0) {
              await new Promise<void>(r => requestAnimationFrame(() => r()))
            } else {
              await new Promise<void>(r => setTimeout(r, delay))
            }
            if (document.body.scrollHeight <= window.innerHeight) continue

            window.scrollTo({ top: y, left: 0 })
            if (Math.abs(window.scrollY - y) <= 2) break
          }

          // Re-save so subsequent navigations (back-button to this page) still
          // find a value. scrollBehavior deleted the key when handing the work
          // to us, and scroll-save's natural scroll listener is suppressed while
          // __scrollRestoring is true, so we need to write back ourselves.
          try { sessionStorage.setItem('scroll:' + to.fullPath, String(y)) } catch {}
        } finally {
          // Release the suppression flag with a small grace window so any
          // in-flight scroll event from the last scrollTo doesn't get saved.
          setTimeout(() => { window.__scrollRestoring = false }, 250)
        }
      })()
    })
  })
})
