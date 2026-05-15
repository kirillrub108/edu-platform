import type { RouterConfig } from '@nuxt/schema'

export default <RouterConfig>{
  scrollBehavior(to, _from, _savedPosition) {
    // Hash anchor
    if (to.hash) return { el: to.hash, top: 80, behavior: 'smooth' }

    // Check our own sessionStorage — if there's a saved position this is
    // a revisit (back/forward or refresh); let restoreScroll() in onMounted handle it.
    // Return false only if we actually have something to restore.
    if (typeof sessionStorage !== 'undefined') {
      try {
        const saved = sessionStorage.getItem('scroll:' + to.fullPath)
        if (saved && Number(saved) > 0) return false
      } catch { /* private mode */ }
    }

    return { top: 0, left: 0 }
  },
}