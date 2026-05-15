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

  router.beforeEach((_, from) => { if (from.matched.length) save(from.fullPath) })
  window.addEventListener('scroll', onScroll, { passive: true })
  window.addEventListener('beforeunload', () => { save(router.currentRoute.value.fullPath) })
})
