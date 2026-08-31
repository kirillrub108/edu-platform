/**
 * Live course-access updates for the student cabinet (DECISIONS §62). What
 * needs pinning: it opens the stream with credentials (the httpOnly cookie is
 * the only auth EventSource can carry), it refetches on every message, and it
 * closes on unmount — a leaked EventSource keeps reconnecting forever after the
 * user leaves the cabinet.
 */
import { createApp, defineComponent, h } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useCourseAccessStream } from '~/composables/useCourseAccessStream'

interface FakeSource {
  url: string
  withCredentials: boolean
  closed: boolean
  onmessage: ((ev: MessageEvent) => void) | null
}

let sources: FakeSource[] = []

class FakeEventSource implements FakeSource {
  url: string
  withCredentials: boolean
  closed = false
  onmessage: ((ev: MessageEvent) => void) | null = null

  constructor(url: string, init?: { withCredentials?: boolean }) {
    this.url = url
    this.withCredentials = init?.withCredentials ?? false
    sources.push(this)
  }

  close(): void {
    this.closed = true
  }
}

// Plain createApp rather than @vue/test-utils — that package is not installed
// and npm is off-limits here (see CLAUDE.md).
const mountWith = (onChange: () => void) => {
  const app = createApp(
    defineComponent({
      setup() {
        useCourseAccessStream(onChange)
        return () => h('div')
      },
    }),
  )
  app.mount(document.createElement('div'))
  return app
}

beforeEach(() => {
  sources = []
  vi.stubGlobal('EventSource', FakeEventSource)
  vi.stubGlobal('useRuntimeConfig', () => ({ public: { apiBase: 'http://api.test' } }))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('useCourseAccessStream', () => {
  it('opens the cabinet stream with credentials', () => {
    mountWith(vi.fn())

    expect(sources).toHaveLength(1)
    expect(sources[0]!.url).toBe('http://api.test/students/courses/stream')
    expect(sources[0]!.withCredentials).toBe(true)
  })

  it('refetches on every message', () => {
    const onChange = vi.fn()
    mountWith(onChange)

    sources[0]!.onmessage?.(new MessageEvent('message', { data: '{"event":"granted"}' }))
    sources[0]!.onmessage?.(new MessageEvent('message', { data: '{"event":"revoked"}' }))

    expect(onChange).toHaveBeenCalledTimes(2)
  })

  it('closes the stream on unmount', () => {
    const app = mountWith(vi.fn())

    app.unmount()

    expect(sources[0]!.closed).toBe(true)
  })
})
