export default defineNuxtPlugin(() => {
  const router = useRouter()
  const KEY = 'edu_scroll'

  const load = (): Record<string, number> => {
    try { return JSON.parse(sessionStorage.getItem(KEY) ?? '{}') } catch { return {} }
  }

  const save = (path: string) => {
    const map = load()
    map[path] = window.scrollY
    sessionStorage.setItem(KEY, JSON.stringify(map))
  }

  const restore = (path: string) => {
    const y = load()[path]
    if (typeof y !== 'number' || y === 0) return

    // Retry until the page has expanded enough to scroll to the target position.
    // Needed for pages with async data (lessons, dashboard) whose content loads
    // after the initial render, making an early scrollTo silently fail.
    let attempts = 0
    const tryRestore = () => {
      window.scrollTo({ top: y, behavior: 'instant' })
      if (window.scrollY < y - 1 && attempts++ < 10) {
        setTimeout(tryRestore, 100)
      }
    }
    nextTick(() => requestAnimationFrame(tryRestore))
  }

  router.beforeEach((_, from) => { save(from.path) })
  router.afterEach(to => { restore(to.path) })
  window.addEventListener('beforeunload', () => { save(router.currentRoute.value.path) })
})
