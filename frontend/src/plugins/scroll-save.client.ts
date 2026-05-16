export default defineNuxtPlugin(() => {
  const router = useRouter()

  if ('scrollRestoration' in history) {
    history.scrollRestoration = 'manual'
  }

  const save = (fullPath: string) => {
    try {
      sessionStorage.setItem('scroll:' + fullPath, String(window.scrollY))
    } catch {
      // sessionStorage unavailable
    }
  }

  let timer: ReturnType<typeof setTimeout> | null = null
  const onScroll = () => {
    if (timer) clearTimeout(timer)   // ← debounce: сбрасываем при каждом событии
    timer = setTimeout(() => {
      // Don't overwrite the saved value while restoreScroll() is programmatically
      // retrying scrollTo on a still-growing page — intermediate clamped scrollY
      // values would corrupt the target we're trying to reach.
      if (!(window as any).__scrollRestoring) {
        save(router.currentRoute.value.fullPath)
      }
      timer = null
    }, 150)
  }

  // Save only when actually leaving the current page. Nuxt fires an internal
  // self-navigation (from.fullPath === to.fullPath) right after hydration; if
  // we save on that, window.scrollY === 0 (page just mounted, restore hasn't
  // run yet) overwrites the value beforeunload wrote on the previous reload.
  router.beforeEach((to, from) => {
    if (from.matched.length && from.fullPath !== to.fullPath) save(from.fullPath)
  })
  window.addEventListener('scroll', onScroll, { passive: true })
  window.addEventListener('beforeunload', () => { save(router.currentRoute.value.fullPath) })
})
