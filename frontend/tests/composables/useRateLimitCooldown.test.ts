/**
 * The cooldown behind the "send the deletion link" button (and the 429 handler
 * on login/register). What needs pinning: `start` counts a known cooldown down
 * to zero and stops there, `triggerFrom429` prefers the server's Retry-After
 * and falls back when it is missing or junk, and the interval is dropped with
 * the scope so a countdown cannot outlive the page.
 */
import { effectScope, type EffectScope } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useRateLimitCooldown } from '~/composables/useRateLimitCooldown'

const FALLBACK = 30

let scope: EffectScope

const run = () => {
  scope = effectScope()
  return scope.run(() => useRateLimitCooldown())!
}

const errorWithRetryAfter = (value: string | null) => ({
  response: { headers: { get: (name: string) => (name === 'Retry-After' ? value : null) } },
})

beforeEach(() => vi.useFakeTimers())

afterEach(() => {
  scope?.stop()
  vi.useRealTimers()
})

describe('useRateLimitCooldown', () => {
  it('starts at zero', () => {
    expect(run().remaining.value).toBe(0)
  })

  it('counts a known cooldown down and stops at zero', () => {
    const { remaining, start } = run()

    start(60)
    expect(remaining.value).toBe(60)

    vi.advanceTimersByTime(1000)
    expect(remaining.value).toBe(59)

    vi.advanceTimersByTime(59_000)
    expect(remaining.value).toBe(0)

    // The interval is cleared, so it never goes negative.
    vi.advanceTimersByTime(5000)
    expect(remaining.value).toBe(0)
  })

  it('restarts instead of stacking intervals', () => {
    const { remaining, start } = run()

    start(60)
    vi.advanceTimersByTime(2000)
    start(10)
    vi.advanceTimersByTime(1000)

    expect(remaining.value).toBe(9)
  })

  it('takes the seconds from Retry-After', () => {
    const { remaining, triggerFrom429 } = run()

    triggerFrom429(errorWithRetryAfter('12'))

    expect(remaining.value).toBe(12)
  })

  it.each([['not-a-number'], [null], ['0'], ['-5']])(
    'falls back when Retry-After is %s',
    (header) => {
      const { remaining, triggerFrom429 } = run()

      triggerFrom429(errorWithRetryAfter(header))

      expect(remaining.value).toBe(FALLBACK)
    },
  )

  it('falls back on an error with no response at all', () => {
    const { remaining, triggerFrom429 } = run()

    triggerFrom429(new Error('network'))

    expect(remaining.value).toBe(FALLBACK)
  })

  it('stops counting once the scope is disposed', () => {
    const { remaining, start } = run()

    start(60)
    scope.stop()
    vi.advanceTimersByTime(5000)

    expect(remaining.value).toBe(60)
  })
})
