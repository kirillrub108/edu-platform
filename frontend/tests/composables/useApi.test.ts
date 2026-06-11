/**
 * Unit tests for the cookie-based useApi composable — isolated, no component
 * mounting.
 *
 * Auth is httpOnly-cookie + double-submit CSRF, NOT Authorization: Bearer (no
 * token ever reaches JS). So these tests assert the cookie-model behaviour:
 *   - state-changing requests ride credentials: 'include' and forward the
 *     csrf_token cookie as X-CSRF-Token;
 *   - a 401 triggers exactly one /auth/refresh (singleflight), then one retry of
 *     the original request;
 *   - if refresh fails, the session is cleared, we redirect to /login, and the
 *     original 401 propagates.
 *
 * Strategy:
 * - Mock 'ofetch' so all network goes through a vi.fn we control. The client
 *   sends no Authorization header to distinguish calls by, so a 401 is keyed off
 *   request state (the cookie not yet refreshed) — mirroring the opaque,
 *   server-set cookie of the real flow.
 * - Re-stub Nuxt auto-imports (useAuthStore, useRuntimeConfig, navigateTo) per
 *   test. The real store exposes only clearSession to useApi, so that's all the
 *   stub provides.
 * - vi.resetModules() in beforeEach so useApi.ts re-evaluates and the
 *   module-private `refreshPromise` singleflight cache is fresh between tests.
 *   Without this, a lingering in-flight refresh from one test would
 *   short-circuit the singleflight check in the next.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// Mutable fetch mock the tests reassign per scenario.
const fetchMock = vi.fn()

vi.mock('ofetch', () => ({
  $fetch: (...args: unknown[]) => fetchMock(...args),
}))

const navigateToMock = vi.fn(async () => undefined)
const clearSessionMock = vi.fn()

const installGlobals = (): void => {
  vi.stubGlobal('useRuntimeConfig', () => ({ public: { apiBase: 'http://api.test' } }))
  vi.stubGlobal('useAuthStore', () => ({ clearSession: clearSessionMock }))
  vi.stubGlobal('navigateTo', navigateToMock)
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
  clearSessionMock.mockClear()
  // Reset the cookie jar to a plain, writable string so getCsrfToken() reads a
  // clean slate and a test can assign a single cookie deterministically.
  Object.defineProperty(document, 'cookie', { value: '', writable: true, configurable: true })
  installGlobals()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('useApi.apiFetch', () => {
  it('forwards the csrf_token cookie as X-CSRF-Token on state-changing requests, with credentials included', async () => {
    document.cookie = 'csrf_token=csrf-xyz'
    fetchMock.mockResolvedValueOnce({ ok: true })

    const useApi = await loadUseApi()
    const { apiFetch } = useApi()
    const out = await apiFetch('/lessons', { method: 'POST', body: { title: 'x' } })

    expect(out).toEqual({ ok: true })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [path, opts] = fetchMock.mock.calls[0] as [
      string,
      { credentials?: string; headers: Record<string, string> },
    ]
    expect(path).toBe('/lessons')
    expect(opts.credentials).toBe('include')
    expect(opts.headers['X-CSRF-Token']).toBe('csrf-xyz')
  })

  it('on 401: refreshes once, then retries the original request', async () => {
    // The stale cookie 401s until /auth/refresh rotates it; the retry then
    // succeeds. There's no Authorization header to key off — the server-set
    // cookie is opaque to JS — so we model it with a `refreshed` flag.
    let refreshed = false
    fetchMock.mockImplementation(async (url: string) => {
      if (url === '/auth/refresh') {
        refreshed = true
        return { ok: true }
      }
      if (!refreshed) throw make401()
      return { ok: true, fresh: true }
    })

    const useApi = await loadUseApi()
    const { apiFetch } = useApi()
    const out = await apiFetch<{ ok: true; fresh: boolean }>('/protected')

    expect(out.ok).toBe(true)
    expect(out.fresh).toBe(true)
    const refreshCalls = fetchMock.mock.calls.filter(([u]) => u === '/auth/refresh')
    expect(refreshCalls).toHaveLength(1)
    // /protected hit twice: the initial 401, then the retry after refresh.
    const protectedCalls = fetchMock.mock.calls.filter(([u]) => u === '/protected')
    expect(protectedCalls).toHaveLength(2)
  })

  it('SINGLEFLIGHT: N parallel 401s trigger refresh exactly once', async () => {
    let refreshResolve: ((v: unknown) => void) | null = null
    const refreshPending = new Promise<unknown>(r => {
      refreshResolve = r
    })
    let refreshHits = 0
    let refreshed = false

    fetchMock.mockImplementation(async (url: string) => {
      if (url === '/auth/refresh') {
        refreshHits += 1
        refreshed = true
        // Hold the refresh open until we explicitly resolve it. This widens the
        // singleflight window so the test would actually FAIL if useApi
        // double-fired the refresh — every concurrent 401 would race here.
        return refreshPending
      }
      if (!refreshed) throw make401()
      return { ok: true }
    })

    const useApi = await loadUseApi()
    const { apiFetch } = useApi()

    // Fire 5 parallel requests; all should 401 before any refresh resolves.
    const inFlight = Promise.all(
      Array.from({ length: 5 }, (_, i) => apiFetch<{ ok: true }>(`/p${i}`)),
    )

    // Let microtasks run so every 401 gets routed into tryRefresh, where
    // singleflight either reuses or duplicates the in-flight refresh.
    for (let i = 0; i < 20; i++) await Promise.resolve()

    expect(refreshHits).toBe(1)

    // Now resolve refresh so the 5 retries can land.
    refreshResolve!({ ok: true })

    const results = await inFlight
    expect(results).toHaveLength(5)
    // Still exactly one refresh after everything settles.
    expect(refreshHits).toBe(1)
    for (const r of results) expect(r.ok).toBe(true)
  })

  it('on failed refresh: clears session, navigates to /login, propagates the error', async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url === '/auth/refresh') {
        // Refresh itself rejects — simulates an invalid/expired refresh token.
        // tryRefresh catches and resolves to false; the outer 401 handler then
        // clears session + redirects and rethrows the original 401.
        throw new Error('refresh denied')
      }
      throw make401()
    })

    const useApi = await loadUseApi()
    const { apiFetch } = useApi()

    await expect(apiFetch('/protected')).rejects.toMatchObject({
      response: { status: 401 },
    })

    expect(clearSessionMock).toHaveBeenCalled()
    expect(navigateToMock).toHaveBeenCalledWith('/login')
  })
})
