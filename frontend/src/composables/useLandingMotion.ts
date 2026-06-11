import type { Ref } from 'vue'

// Port of design_handoff_edllm/app.js into a Vue composable. Drives every
// landing interaction: sticky-nav state, cursor glow, the hero 3D tilt, card
// micro-tilt, background parallax, scroll-reveal (with stagger), count-up stats
// and the live audio wave. All work is gated behind prefers-reduced-motion and
// (for pointer effects) coarse pointers, and every listener / rAF loop is torn
// down on unmount so SPA navigation away from the landing leaks nothing.
//
// `root` is the `.ldg` wrapper element. CSS custom properties (--tilt-max,
// --anim-speed) live on that element, so we read them from it rather than from
// documentElement like the original did.

export function useLandingMotion(root: Ref<HTMLElement | null>): void {
  if (!import.meta.client) return

  const cleanups: Array<() => void> = []
  let rafs: number[] = []

  onMounted(() => {
    const el = root.value
    if (!el) return

    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const coarse = window.matchMedia('(pointer: coarse)').matches

    const cssVar = (name: string, fallback: number): number => {
      const v = parseFloat(getComputedStyle(el).getPropertyValue(name))
      return Number.isNaN(v) ? fallback : v
    }
    const on = (
      target: Window | HTMLElement,
      type: string,
      handler: EventListenerOrEventListenerObject,
      opts?: AddEventListenerOptions,
    ) => {
      target.addEventListener(type, handler, opts)
      cleanups.push(() => target.removeEventListener(type, handler, opts))
    }
    const loop = (fn: () => void) => {
      let stopped = false
      const tick = () => {
        if (stopped) return
        fn()
        rafs.push(requestAnimationFrame(tick))
      }
      rafs.push(requestAnimationFrame(tick))
      cleanups.push(() => { stopped = true })
    }

    /* ---------- sticky nav state ---------- */
    const nav = el.querySelector<HTMLElement>('header.nav')
    const onScrollNav = () => {
      if (!nav) return
      nav.classList.toggle('scrolled', window.scrollY > 12)
    }
    onScrollNav()

    /* ---------- cursor-reactive glow ---------- */
    const glow = el.querySelector<HTMLElement>('.cursor-glow')
    if (glow && !coarse && !reduce) {
      let gx = window.innerWidth * 0.5
      let gy = window.innerHeight * 0.3
      let tx = gx
      let ty = gy
      on(window, 'pointermove', ((e: PointerEvent) => { tx = e.clientX; ty = e.clientY }) as EventListener, { passive: true })
      loop(() => {
        gx += (tx - gx) * 0.08
        gy += (ty - gy) * 0.08
        glow.style.transform = `translate3d(${gx}px,${gy}px,0)`
      })
    } else if (glow) {
      glow.style.opacity = '0.6'
    }

    /* ---------- 3D tilt on hero player ---------- */
    const stage = el.querySelector<HTMLElement>('.stage')
    const player = el.querySelector<HTMLElement>('.player')
    if (stage && player && !coarse && !reduce) {
      let rect: DOMRect | null = null
      on(stage, 'pointerenter', (() => { rect = stage.getBoundingClientRect() }) as EventListener)
      on(stage, 'pointermove', ((e: PointerEvent) => {
        if (!rect) rect = stage.getBoundingClientRect()
        const max = cssVar('--tilt-max', 9)
        const px = (e.clientX - rect.left) / rect.width - 0.5
        const py = (e.clientY - rect.top) / rect.height - 0.5
        const ry = px * max * 2
        const rx = 8 - py * max * 2
        player.style.transform = `rotateX(${rx.toFixed(2)}deg) rotateY(${ry.toFixed(2)}deg)`
      }) as EventListener)
      on(stage, 'pointerleave', (() => {
        player.style.transform = 'rotateX(8deg) rotateY(0deg)'
      }) as EventListener)
    }

    /* ---------- 3D tilt micro on cards ---------- */
    if (!coarse && !reduce) {
      el.querySelectorAll<HTMLElement>('.step, .adv, .pack').forEach((card) => {
        on(card, 'pointermove', ((e: PointerEvent) => {
          const max = cssVar('--tilt-max', 9) * 0.5
          const r = card.getBoundingClientRect()
          const px = (e.clientX - r.left) / r.width - 0.5
          const py = (e.clientY - r.top) / r.height - 0.5
          card.style.transform =
            `translateY(-8px) perspective(700px) rotateX(${(-py * max).toFixed(2)}deg) rotateY(${(px * max).toFixed(2)}deg)`
        }) as EventListener)
        on(card, 'pointerleave', (() => { card.style.transform = '' }) as EventListener)
      })
    }

    /* ---------- parallax background layers ---------- */
    const layers = Array.from(el.querySelectorAll<HTMLElement>('[data-parallax]'))
    let sy = window.scrollY
    const applyParallax = () => {
      const speed = cssVar('--anim-speed', 1)
      layers.forEach((layer) => {
        const f = parseFloat(layer.getAttribute('data-parallax') || '0') || 0
        layer.style.translate = `0 ${(sy * f * speed).toFixed(1)}px`
      })
    }
    const onScroll = () => {
      sy = window.scrollY
      onScrollNav()
      if (!reduce) applyParallax()
    }
    on(window, 'scroll', (() => { requestAnimationFrame(onScroll) }) as EventListener, { passive: true })
    if (!reduce) applyParallax()

    /* ---------- scroll reveal with stagger (base visible; hide below-fold) ---------- */
    const reveals = Array.from(el.querySelectorAll<HTMLElement>('.reveal'))
    if (!reduce) {
      el.classList.add('motion')
      const vh0 = window.innerHeight
      const pending: HTMLElement[] = []
      reveals.forEach((r) => {
        if (r.getBoundingClientRect().top > vh0 * 0.9) {
          r.classList.add('r-hidden')
          pending.push(r)
        }
      })
      const revealNow = (node: HTMLElement) => {
        const group = node.parentElement
        const sibs = group ? Array.from(group.querySelectorAll<HTMLElement>(':scope > .reveal')) : [node]
        const idx = sibs.indexOf(node)
        node.style.animationDelay = `${idx > 0 ? Math.min(idx, 6) * 75 : 0}ms`
        node.classList.remove('r-hidden')
        node.classList.add('in')
      }
      let revTick = false
      const checkReveals = () => {
        revTick = false
        const vh = window.innerHeight
        for (let i = pending.length - 1; i >= 0; i--) {
          const node = pending[i]
          const r = node.getBoundingClientRect()
          if (r.top < vh * 0.88 && r.bottom > 0) {
            revealNow(node)
            pending.splice(i, 1)
          }
        }
      }
      const queueReveals = () => {
        if (revTick) return
        revTick = true
        requestAnimationFrame(checkReveals)
      }
      on(window, 'scroll', queueReveals as EventListener, { passive: true })
      on(window, 'resize', queueReveals as EventListener)
      checkReveals()
      const t = setTimeout(checkReveals, 300)
      cleanups.push(() => clearTimeout(t))
      on(window, 'load', checkReveals as EventListener)
    }

    /* ---------- count-up stats ---------- */
    let counted = false
    const bannerStats = el.querySelector<HTMLElement>('.stats')
    const runCount = () => {
      if (counted) return
      counted = true
      el.querySelectorAll<HTMLElement>('.big[data-to]').forEach((node) => {
        const to = parseFloat(node.getAttribute('data-to') || '0')
        const from = parseFloat(node.getAttribute('data-from') || '0') || 0
        const suffix = node.getAttribute('data-suffix') || ''
        const dur = reduce ? 0 : 1200
        let start: number | null = null
        const frame = (t: number) => {
          if (start === null) start = t
          const p = dur ? Math.min((t - start) / dur, 1) : 1
          const eased = 1 - Math.pow(1 - p, 3)
          const val = Math.round(from + (to - from) * eased)
          node.textContent = val + suffix
          if (p < 1) requestAnimationFrame(frame)
        }
        requestAnimationFrame(frame)
      })
    }
    if (bannerStats) {
      if (reduce) {
        runCount()
      } else {
        const checkCount = () => {
          if (counted) return
          const r = bannerStats.getBoundingClientRect()
          if (r.top < window.innerHeight * 0.82 && r.bottom > 0) runCount()
        }
        on(window, 'scroll', checkCount as EventListener, { passive: true })
        checkCount()
      }
    }

    /* ---------- live audio wave (bars are pre-rendered in the template) ---------- */
    const wave = el.querySelector<HTMLElement>('.wave')
    if (wave) {
      const bars = Array.from(wave.querySelectorAll<HTMLElement>('span'))
      const BARS = bars.length
      if (reduce) {
        bars.forEach((b, i) => { b.style.height = `${20 + Math.abs(Math.sin(i * 0.6)) * 60}%` })
      } else {
        let phase = 0
        loop(() => {
          const speed = cssVar('--anim-speed', 1)
          phase += 0.07 * speed
          for (let j = 0; j < BARS; j++) {
            const env = Math.sin((j / BARS) * Math.PI)
            const v =
              Math.sin(phase + j * 0.5) * 0.5 +
              Math.sin(phase * 1.7 + j * 0.23) * 0.3 +
              Math.sin(phase * 0.6 + j * 0.9) * 0.2
            const h = 14 + (v * 0.5 + 0.5) * 78 * (0.45 + env * 0.55)
            bars[j].style.height = `${h.toFixed(1)}%`
          }
        })
      }
    }
  })

  onUnmounted(() => {
    rafs.forEach((id) => cancelAnimationFrame(id))
    rafs = []
    cleanups.forEach((fn) => fn())
    cleanups.length = 0
  })
}
