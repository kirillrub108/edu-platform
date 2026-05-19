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
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      if (!(window as any).__scrollRestoring) {
        save(router.currentRoute.value.fullPath)
      }
      timer = null
    }, 150)
  }

  router.beforeEach((to, from) => {
    if (from.matched.length && from.fullPath !== to.fullPath) save(from.fullPath)
  })
  window.addEventListener('scroll', onScroll, { passive: true })
  window.addEventListener('beforeunload', () => { save(router.currentRoute.value.fullPath) })
})
