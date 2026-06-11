import type { Directive } from 'vue'

// `v-reveal`: fade + lift an element the first time it scrolls into view.
// Intentionally for BELOW-THE-FOLD content only — it sets the hidden state in
// `mounted`, which runs after the prerendered HTML paints, so off-screen
// elements never flash. Honors prefers-reduced-motion (shows immediately, no
// transform) and needs no animation library. Cleans up its observer on unmount.

const observers = new WeakMap<HTMLElement, IntersectionObserver>()

function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

export function useScrollReveal(): Directive<HTMLElement> {
  return {
    mounted(el) {
      if (!import.meta.client || prefersReducedMotion()) return

      el.classList.add('reveal')
      const delay = el.dataset.revealDelay
      if (delay) el.style.transitionDelay = `${delay}ms`

      const io = new IntersectionObserver(
        (entries, obs) => {
          for (const entry of entries) {
            if (!entry.isIntersecting) continue
            entry.target.classList.add('reveal-in')
            obs.unobserve(entry.target)
          }
        },
        { threshold: 0.15, rootMargin: '0px 0px -8% 0px' },
      )
      io.observe(el)
      observers.set(el, io)
    },
    unmounted(el) {
      observers.get(el)?.disconnect()
      observers.delete(el)
    },
  }
}
