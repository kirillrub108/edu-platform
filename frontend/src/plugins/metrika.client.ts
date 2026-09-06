// Yandex.Metrika hits — client only.
//
// tag.js + ym(id,'init',{defer:true}) live in the static head snippet
// (nuxt.config.ts) so Metrika's counter check finds them in the served HTML.
// defer:true means Metrika sends no view on its own — this plugin sends every
// page view manually on router.afterEach. The gate (anonymous OR teacher) lives
// in useMetrika().shouldTrack so it isn't duplicated here.

export default defineNuxtPlugin((nuxtApp) => {
  const { counterId, shouldTrack } = useMetrika()
  // Empty metrikaId (dev/test) → nothing is wired up at all.
  if (!counterId) return

  const auth = useAuthStore()
  const router = useRouter()

  // Guards a hit being sent twice for the same route — the initial navigation
  // can trigger both the app:mounted hit and a router.afterEach hit.
  let lastHitPath: string | null = null

  const sendHit = (toPath: string, fromPath?: string): void => {
    // Re-checked per navigation: a SPA login as a student stops hits, a logout
    // back to anonymous resumes them.
    if (!shouldTrack()) return
    if (toPath === lastHitPath) return
    lastHitPath = toPath
    const origin = window.location.origin
    try {
      // window.ym is absent if an ad blocker stripped the snippet — no-op.
      window.ym?.(counterId, 'hit', origin + toPath, {
        title: document.title,
        ...(fromPath ? { referer: origin + fromPath } : {}),
      })
    } catch {
      /* analytics must never break the app */
    }
  }

  // The role is only known after the session is restored. Hold every hit that
  // arrives before that resolves (only the latest survives) so a hard refresh
  // inside a student cabinet can't leak a hit before we know the role.
  let ready = false
  let pending: { to: string; from?: string } | null = null

  const dispatchHit = (toPath: string, fromPath?: string): void => {
    if (!ready) {
      pending = { to: toPath, from: fromPath }
      return
    }
    sendHit(toPath, fromPath)
  }

  void auth.fetchMe().finally(() => {
    ready = true
    if (pending) {
      sendHit(pending.to, pending.from)
      pending = null
    }
  })

  // First hit waits for app:mounted so useHead has flushed document.title for
  // the initial route before we read it.
  nuxtApp.hook('app:mounted', () => {
    nextTick(() => {
      dispatchHit(router.currentRoute.value.fullPath)
    })
  })

  router.afterEach((to, from) => {
    nextTick(() => {
      const toPath = to.fullPath
      const fromPath = from.fullPath !== toPath ? from.fullPath : undefined
      dispatchHit(toPath, fromPath)
    })
  })
})
