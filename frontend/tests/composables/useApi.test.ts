/**
 * Unit tests for useApi composable — isolated, no component mounting.
 *
 * Strategy:
 * - Mock 'ofetch' so all network goes through a vi.fn we control.
 * - Re-stub Nuxt auto-imports (useAuthStore, useRuntimeConfig, navigateTo)
 *   per test with stateful fakes so we can observe token rotation.
 * - vi.resetModules() in beforeEach so useApi.ts re-evaluates and the
 *   module-private `refreshPromise` cache is fresh between tests. Without
 *   this, a lingering in-flight refresh from one test would short-circuit
 *   the singleflight check in the next.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

interface Tokens {
  access_token: string
  refresh_token: string
  token_type: string
}

// Mutable fetch mock the tests reassign per scenario.
const fetchMock = vi.fn()

vi.mock('ofetch', () => ({
  $fetch: (...args: unknown[]) => fetchMock(...args),
}))

// Stateful auth store with controllable tokens.
let currentAccess: string | null = null
let currentRefresh: string | null = null
let clearedCount = 0

const navigateToMock = vi.fn(async () => undefined)

const installGlobals = (): void => {
  vi.stubGlobal('useRuntimeConfig', () => ({ public: { apiBase: 'http://api.test' } }))
  vi.stubGlobal('useAuthStore', () => ({
    getAccessToken: () => currentAccess,
    getRefreshToken: () => currentRefresh,
    persistTokens: (t: Tokens) => {
      currentAccess = t.access_token
      currentRefresh = t.refresh_token
    },
    clearSession: () => {
      currentAccess = null
      currentRefresh = null
      clearedCount += 1
    },
  }))
  vi.stubGlobal('navigateTo', navigateToMock)
}

// Build a JWT-shaped token whose exp is comfortably in the future, so the
// proactive-refresh check in useApi.ts treats it as still valid.
const futureJwt = (id: string): string => {
  const header = btoa(JSON.stringify({ alg: 'none', typ: 'JWT' }))
  const payload = btoa(
    JSON.stringify({ sub: id, exp: Math.floor(Date.now() / 1000) + 3600 }),
  )
  return `${header}.${payload}.sig`
}

const make401 = (): Error => {
  const err = new Error('Unauthorized') as Error & { response?: { status: number } }
  err.response = { status: 401 }
  return err
}

const loadUseApi = async (): Promise<typeof import('../../src/composables/useApi').useApi> => {
  const mod = await import('../../src/composables/useApi')
  return mod.useApi
}

beforeEach(() => {
  vi.resetModules()
  fetchMock.mockReset()
  navigateToMock.mockClear()
  currentAccess = null
  currentRefresh = null
  clearedCount = 0
  installGlobals()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('useApi.apiFetch', () => {
  it('attaches Authorization: Bearer <access> when a token is present', async () => {
    currentAccess = futureJwt('user-1')
    currentRefresh = 'r-1'
    fetchMock.mockResolvedValueOnce({ ok: true })

    const useApi = await loadUseApi()
    const { apiFetch } = useApi()
    const out = await apiFetch('/hello')

    expect(out).toEqual({ ok: true })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [, opts] = fetchMock.mock.calls[0]
    expect((opts as { headers: Record<string, string> }).headers.Authorization).toBe(
      `Bearer ${currentAccess}`,
    )
  })

  it('on 401: refreshes once, then retries the original request with the new token', async () => {
    currentAccess = futureJwt('user-1')
    currentRefresh = 'r-1'
    // Capture the original token before persistTokens rotates currentAccess
    // mid-test, so the 401 condition stays pinned to the pre-refresh value.
    const original = currentAccess

    fetchMock.mockImplementation(async (url: string, opts: { headers?: Record<string, string> }) => {
      if (url === '/auth/refresh') {
        return { access_token: futureJwt('user-1-new'), refresh_token: 'r-2', token_type: 'bearer' }
      }
      const bearer = opts.headers?.Authorization
      if (bearer === `Bearer ${original}`) throw make401()
      return { ok: true, who: bearer }
    })

    const useApi = await loadUseApi()
    const { apiFetch } = useApi()
    const out = await apiFetch<{ ok: true; who: string }>('/protected')

    expect(out.ok).toBe(true)
    const refreshCalls = fetchMock.mock.calls.filter(([u]) => u === '/auth/refresh')
    expect(refreshCalls).toHaveLength(1)
    expect(out.who).toBe(`Bearer ${currentAccess}`)
    expect(out.who).not.toBe(`Bearer ${original}`)
  })

  it('SINGLEFLIGHT: N parallel 401s trigger refresh exactly once', async () => {
    currentAccess = futureJwt('user-1')
    currentRefresh = 'r-1'
    const original = currentAccess

    let refreshResolve: ((v: Tokens) => void) | null = null
    const refreshPending = new Promise<Tokens>(r => {
      refreshResolve = r
    })
    let refreshHits = 0

    fetchMock.mockImplementation(async (url: string, opts: { headers?: Record<string, string> }) => {
      if (url === '/auth/refresh') {
        refreshHits += 1
        // Hold the refresh open until we explicitly resolve it. This widens
        // the singleflight window so the test would actually FAIL if useApi
        // double-fired the refresh — every concurrent 401 would race here.
        return refreshPending
      }
      const bearer = opts.headers?.Authorization
      if (bearer === `Bearer ${original}`) throw make401()
      return { ok: true, who: bearer }
    })

    const useApi = await loadUseApi()
    const { apiFetch } = useApi()

    // Fire 5 parallel requests; all should 401 before any refresh resolves.
    const inFlight = Promise.all(
      Array.from({ length: 5 }, (_, i) => apiFetch<{ ok: true; who: string }>(`/p${i}`)),
    )

    // Let microtasks run so every 401 gets routed into the refresh branch
    // and into tryRefresh (where singleflight either reuses or duplicates).
    for (let i = 0; i < 20; i++) await Promise.resolve()

    expect(refreshHits).toBe(1)

    // Now resolve refresh so the 5 retries can land.
    refreshResolve!({
      access_token: futureJwt('user-1-new'),
      refresh_token: 'r-2',
      token_type: 'bearer',
    })

    const results = await inFlight
    expect(results).toHaveLength(5)
    // Still exactly one refresh after everything settles.
    expect(refreshHits).toBe(1)
    for (const r of results) expect(r.ok).toBe(true)
  })

  it('on failed refresh: clears session, navigates to /login, propagates the error', async () => {
    currentAccess = futureJwt('user-1')
    currentRefresh = 'r-bad'
    const original = currentAccess

    fetchMock.mockImplementation(async (url: string, opts: { headers?: Record<string, string> }) => {
      if (url === '/auth/refresh') {
        // Refresh itself rejects — simulates an invalid/expired refresh token.
        // useApi catches inside tryRefresh and resolves to null; the outer
        // 401 handler then clears session + redirects.
        throw new Error('refresh denied')
      }
      const bearer = opts.headers?.Authorization
      if (bearer === `Bearer ${original}`) throw make401()
      return { ok: true }
    })

    const useApi = await loadUseApi()
    const { apiFetch } = useApi()

    await expect(apiFetch('/protected')).rejects.toMatchObject({
      response: { status: 401 },
    })

    expect(clearedCount).toBeGreaterThanOrEqual(1)
    expect(navigateToMock).toHaveBeenCalledWith('/login')
    expect(currentAccess).toBeNull()
    expect(currentRefresh).toBeNull()
  })
})
