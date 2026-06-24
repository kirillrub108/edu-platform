// Yandex.Metrika loader — client only.
//
// SPA-adapted: instead of the static <script>+auto-hit snippet we (1) lazily
// inject tag.js the first moment the visitor is eligible, and (2) send every
// page view manually on router.afterEach. The gate (anonymous OR teacher) lives
// in useMetrika().shouldTrack so it isn't duplicated here.

const TAG_SRC = 'https://mc.yandex.ru/metrika/tag.js'

export default defineNuxtPlugin(() => {
  const { counterId, shouldTrack } = useMetrika()
  // Empty NUXT_PUBLIC_METRIKA_ID (dev/test) → nothing is wired up at all.
  if (!counterId) return

  const auth = useAuthStore()
  const router = useRouter()

  // tag.js is fetched only after shouldTrack() is first true, so a student who
  // lands straight in their cabinet never loads the counter at all.
  let counterLoaded = false

  const ensureCounter = (): void => {
    if (counterLoaded) return
    counterLoaded = true

    // Queue stub so ym() calls made before tag.js finishes loading are buffered
    // (mirrors Yandex's own loader).
    if (typeof window.ym !== 'function') {
      const stub: typeof window.ym & { a?: unknown[][]; l?: number } = function (
        ...args: unknown[]
      ) {
        ;(stub.a = stub.a || []).push(args)
      }
      stub.l = Date.now()
      window.ym = stub
    }

    if (!document.querySelector(`script[src="${TAG_SRC}"]`)) {
      const s = document.createElement('script')
      s.async = true
      s.src = TAG_SRC
      document.head.appendChild(s)
    }

    // defer:true suppresses Metrika's automatic first hit — the role isn't known
    // at init time, and we send hits manually below, so the auto-hit would both
    // leak prematurely and double the landing view.
    window.ym?.(counterId, 'init', {
      defer: true,
      clickmap: true,
      trackLinks: true,
      accurateTrackBounce: true,
      webvisor: false,
      ecommerce: 'dataLayer',
    })
  }

  const sendHit = (toPath: string, fromPath?: string): void => {
    // Re-checked per navigation: a SPA login as a student stops hits, a logout
    // back to anonymous resumes them.
    if (!shouldTrack()) return
    ensureCounter()
    const origin = window.location.origin
    window.ym?.(
      counterId,
      'hit',
      origin + toPath,
      fromPath ? { referer: origin + fromPath } : undefined,
    )
  }

  // The role is only known after the session is restored. Probe once (never
  // rejects); hold the very first hit until it resolves so a hard refresh inside
  // a student cabinet can't leak a hit before we know the role.
  let ready = false
  let pending: { to: string; from?: string } | null = null

  void auth.fetchMe().then(() => {
    ready = true
    if (pending) {
      sendHit(pending.to, pending.from)
      pending = null
    }
  })

  router.afterEach((to, from) => {
    const toPath = to.fullPath
    const fromPath = from.fullPath !== toPath ? from.fullPath : undefined
    if (!ready) {
      pending = { to: toPath, from: fromPath }
      return
    }
    sendHit(toPath, fromPath)
  })
})
