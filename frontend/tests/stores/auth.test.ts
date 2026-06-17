/**
 * Auth store — password recovery / change actions.
 *
 * Follows the billing.test.ts pattern: vi.resetModules() + dynamic import so
 * each test gets a fresh module graph, with Nuxt auto-imports (useApi, ref,
 * computed, navigateTo) stubbed as globals.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref, computed } from 'vue'

const fetchMock = vi.fn()

const loadStore = async () => {
  const { createPinia, setActivePinia } = await import('pinia')
  setActivePinia(createPinia())
  const { useAuthStore } = await import('../../src/stores/auth')
  return useAuthStore()
}

beforeEach(() => {
  vi.resetModules()
  fetchMock.mockReset()
  fetchMock.mockResolvedValue(undefined)
  vi.stubGlobal('ref', ref)
  vi.stubGlobal('computed', computed)
  vi.stubGlobal('navigateTo', vi.fn())
  vi.stubGlobal('useApi', () => ({ apiFetch: fetchMock }))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('useAuthStore password flows', () => {
  it('forgotPassword POSTs the email and never branches on the response', async () => {
    const store = await loadStore()
    await store.forgotPassword('user@example.com')

    expect(fetchMock).toHaveBeenCalledWith('/auth/forgot-password', {
      method: 'POST',
      body: { email: 'user@example.com' },
    })
  })

  it('resetPassword POSTs token + new_password', async () => {
    const store = await loadStore()
    await store.resetPassword('raw-token', 'new-password-456')

    expect(fetchMock).toHaveBeenCalledWith('/auth/reset-password', {
      method: 'POST',
      body: { token: 'raw-token', new_password: 'new-password-456' },
    })
  })

  it('changePassword POSTs old_password + new_password', async () => {
    const store = await loadStore()
    await store.changePassword('old-pass-123', 'new-password-456')

    expect(fetchMock).toHaveBeenCalledWith('/auth/change-password', {
      method: 'POST',
      body: { old_password: 'old-pass-123', new_password: 'new-password-456' },
    })
  })

  it('resetPassword propagates an invalid-token error to the caller', async () => {
    fetchMock.mockRejectedValueOnce({ response: { status: 400 } })
    const store = await loadStore()

    await expect(store.resetPassword('bad', 'new-password-456')).rejects.toMatchObject({
      response: { status: 400 },
    })
  })
})
