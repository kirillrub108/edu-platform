/**
 * The student's course list has to pick up access granted while the tab sat in
 * the background (see DECISIONS §62). What needs pinning: it refetches on
 * return, it throttles the focus+visibilitychange pair that fires together on a
 * single alt-tab, it stays quiet while the tab is hidden, and it detaches on
 * unmount — a listener outliving the page would refetch forever.
 */
import { createApp, defineComponent, h } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useRefetchOnFocus } from '~/composables/useRefetchOnFocus'

let visibility: 'visible' | 'hidden' = 'visible'

// Plain createApp rather than @vue/test-utils — that package is not installed
// and npm is off-limits here (see CLAUDE.md).
const mountWith = (refetch: () => unknown, minIntervalMs?: number) => {
  const app = createApp(
    defineComponent({
      setup() {
        useRefetchOnFocus(refetch, minIntervalMs)
        return () => h('div')
      },
    }),
  )
  app.mount(document.createElement('div'))
  return app
}

// happy-dom defines visibilityState on the prototype; redefining it on the
// instance is the version-proof way to drive it from a test.
beforeEach(() => {
  visibility = 'visible'
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    get: () => visibility,
  })
  vi.spyOn(Date, 'now').mockReturnValue(1_000_000)
})

afterEach(() => {
  Reflect.deleteProperty(document, 'visibilityState')
  vi.restoreAllMocks()
})

describe('useRefetchOnFocus', () => {
  it('refetches when the tab regains focus', () => {
    const refetch = vi.fn()
    mountWith(refetch)

    vi.mocked(Date.now).mockReturnValue(1_100_000)
    window.dispatchEvent(new Event('focus'))

    expect(refetch).toHaveBeenCalledTimes(1)
  })

  it('collapses the focus + visibilitychange pair into one call', () => {
    const refetch = vi.fn()
    mountWith(refetch)

    vi.mocked(Date.now).mockReturnValue(1_100_000)
    window.dispatchEvent(new Event('focus'))
    document.dispatchEvent(new Event('visibilitychange'))

    expect(refetch).toHaveBeenCalledTimes(1)
  })

  it('refetches again once the throttle window has passed', () => {
    const refetch = vi.fn()
    mountWith(refetch, 5000)

    vi.mocked(Date.now).mockReturnValue(1_010_000)
    window.dispatchEvent(new Event('focus'))
    vi.mocked(Date.now).mockReturnValue(1_020_000)
    window.dispatchEvent(new Event('focus'))

    expect(refetch).toHaveBeenCalledTimes(2)
  })

  it('stays quiet while the tab is hidden', () => {
    const refetch = vi.fn()
    mountWith(refetch)

    visibility = 'hidden'
    vi.mocked(Date.now).mockReturnValue(1_100_000)
    document.dispatchEvent(new Event('visibilitychange'))

    expect(refetch).not.toHaveBeenCalled()
  })

  it('detaches its listeners on unmount', () => {
    const refetch = vi.fn()
    const app = mountWith(refetch)

    app.unmount()
    vi.mocked(Date.now).mockReturnValue(1_100_000)
    window.dispatchEvent(new Event('focus'))
    document.dispatchEvent(new Event('visibilitychange'))

    expect(refetch).not.toHaveBeenCalled()
  })
})
