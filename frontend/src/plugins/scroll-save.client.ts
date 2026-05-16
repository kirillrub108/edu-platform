export default defineNuxtPlugin(() => {
  const router = useRouter()
  const slog = (...args: unknown[]) => console.log('[SAVE]', `t=${(performance.now() | 0)}ms`, ...args)
  slog('plugin loaded')

  if ('scrollRestoration' in history) {
    history.scrollRestoration = 'manual'
  }

  const save = (fullPath: string, src: string) => {
    try {
      sessionStorage.setItem('scroll:' + fullPath, String(window.scrollY))
      slog('SAVE', src, '| key=scroll:' + fullPath, '| Y=', window.scrollY)
    } catch {
      // sessionStorage unavailable
    }
  }

  let timer: ReturnType<typeof setTimeout> | null = null
  const onScroll = () => {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      if (!(window as any).__scrollRestoring) {
        save(router.currentRoute.value.fullPath, 'scroll-listener')
      } else {
        slog('scroll-listener SUPPRESSED (__scrollRestoring=true) — scrollY would have been', window.scrollY)
      }
      timer = null
    }, 150)
  }

  router.beforeEach((to, from) => {
    if (from.matched.length && from.fullPath !== to.fullPath) save(from.fullPath, 'router.beforeEach')
  })
  window.addEventListener('scroll', onScroll, { passive: true })
  window.addEventListener('beforeunload', () => { save(router.currentRoute.value.fullPath, 'beforeunload') })
})
