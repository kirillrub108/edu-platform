// Preserve window scroll position across HTML5 Fullscreen API enter/exit.
//
// THE REAL BUG (found via logging):
// When a <video> enters fullscreen, the browser changes window.scrollY BEFORE
// our fullscreenchange handler runs. Why: the video becomes position:fixed and
// leaves the document flow, body.scrollHeight shrinks by the video's height,
// and the browser clamps/re-anchors the scroll position.
// Example from real session: user was at Y=1179 (max scroll, page 2153 tall),
// clicked fullscreen → fullscreenchange handler saw window.scrollY=703 because
// the page had already shrunk to 1677 tall. Saving 703 = wrong restore point.
//
// FIX: maintain `lastUserY` by listening to scroll events and only updating
// when document.fullscreenElement === null. The browser-triggered scroll that
// happens during the fullscreen transition happens AFTER document.fullscreenElement
// is set (per the Fullscreen API spec: state is established before the event
// is dispatched), so this guard correctly filters it out.

declare global {
  interface Window { __scrollRestoring?: boolean }
}

export default defineNuxtPlugin(() => {

  let lastUserY = 0
  let lastUserPath = window.location.pathname + window.location.search + window.location.hash

  // Capture scroll position only when NOT in fullscreen. This filters out
  // the browser's transition-scroll that happens at the moment of fullscreen entry.
  window.addEventListener('scroll', () => {
    const fsEl = document.fullscreenElement
    if (!fsEl) {
      lastUserY = window.scrollY
      lastUserPath = window.location.pathname + window.location.search + window.location.hash
    }
  }, { passive: true })

  const apply = (target: number) => window.scrollTo({ top: target, left: 0 })

  const restore = (target: number, path: string) => {
    window.__scrollRestoring = true

    requestAnimationFrame(() => {
      apply(target)
      requestAnimationFrame(() => apply(target))
    })
    for (const ms of [50, 120, 250, 400, 700, 1000]) {
      setTimeout(() => apply(target), ms)
    }

    setTimeout(() => {
      apply(target)
      try { sessionStorage.setItem('scroll:' + path, String(target)) } catch {}
      setTimeout(() => {
        window.__scrollRestoring = false
      }, 300)
    }, 1200)
  }

  document.addEventListener('fullscreenchange', () => {
    const el = document.fullscreenElement
    if (!el) {
      restore(lastUserY, lastUserPath)
    }
  })

  // Initialize for the corner case where user enters fullscreen immediately
  // after page load without scrolling.
  lastUserY = window.scrollY
})
