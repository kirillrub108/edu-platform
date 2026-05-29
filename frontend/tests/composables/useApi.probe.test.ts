/**
 * Session-probe semantics for the cookie-based useApi:
 *   - A 401 from the /auth/me probe means "anonymous" — it must NOT clear the
 *     session or redirect to /login (otherwise public pages whose header probes
 *     /auth/me bounce anonymous visitors off the landing).
 *   - A 401 from any other endpoint, after refresh fails, MUST still auto-logout.
 *
 * Mocks 'ofetch' so all network goes through a controllable vi.fn. Nuxt
 * auto-imports (useRuntimeConfig/useAuthStore/navigateTo) are stubbed per test.
 * vi.resetModules() keeps the module-private refreshPromise singleflight fresh.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

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

const loadUseApi = async () => (await import('../../src/composables/useApi')).useApi

beforeEach(() => {
  vi.resetModules()
  fetchMock.mockReset()
  navigateToMock.mockClear()
  clearSessionMock.mockClear()
  Object.defineProperty(document, 'cookie', { value: '', writable: true, configurable: true })
  installGlobals()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('useApi — session probe vs real session expiry', () => {
  it('does NOT redirect/clear on a 401 from /auth/me (anonymous probe)', async () => {
    // Every call 401s, including the refresh attempt.
    fetchMock.mockRejectedValue(make401())

    const useApi = await loadUseApi()
    const { apiFetch } = useApi()

    await expect(apiFetch('/auth/me')).rejects.toMatchObject({ response: { status: 401 } })

    expect(navigateToMock).not.toHaveBeenCalled()
    expect(clearSessionMock).not.toHaveBeenCalled()
  })

  it('DOES auto-logout on a 401 from a normal endpoint when refresh fails', async () => {
    fetchMock.mockRejectedValue(make401())

    const useApi = await loadUseApi()
    const { apiFetch } = useApi()

    await expect(apiFetch('/courses/')).rejects.toMatchObject({ response: { status: 401 } })

    expect(clearSessionMock).toHaveBeenCalled()
    expect(navigateToMock).toHaveBeenCalledWith('/login')
  })
})
