/**
 * Notifications store: settings load, optimistic toggle + rollback on failure.
 *
 * Mirrors billing.test.ts: resetModules + dynamic import, Nuxt auto-imports
 * (ref, computed, useApi) stubbed as globals.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { computed, ref } from 'vue'

const fetchMock = vi.fn()

const loadStore = async () => {
  const { createPinia, setActivePinia } = await import('pinia')
  setActivePinia(createPinia())
  const mod = await import('../../src/stores/notifications')
  return { store: mod.useNotificationsStore(), categories: mod.NOTIFICATION_CATEGORIES }
}

const allOn = { notify_content: true, notify_feedback: true, notify_submissions: true }

beforeEach(() => {
  vi.resetModules()
  fetchMock.mockReset()
  vi.stubGlobal('ref', ref)
  vi.stubGlobal('computed', computed)
  vi.stubGlobal('useApi', () => ({ apiFetch: fetchMock }))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('notifications store', () => {
  it('loads settings from the API', async () => {
    fetchMock.mockResolvedValueOnce(allOn)
    const { store } = await loadStore()

    await store.fetchSettings()

    expect(fetchMock).toHaveBeenCalledWith('/notifications/settings')
    expect(store.settings).toEqual(allOn)
    expect(store.error).toBeNull()
  })

  it('surfaces a load failure without throwing', async () => {
    fetchMock.mockRejectedValueOnce(new Error('boom'))
    const { store } = await loadStore()

    await store.fetchSettings()

    expect(store.settings).toBeNull()
    expect(store.error).toBeTruthy()
  })

  it('PATCHes only the toggled category', async () => {
    fetchMock.mockResolvedValueOnce(allOn)
    const { store } = await loadStore()
    await store.fetchSettings()

    fetchMock.mockResolvedValueOnce({ ...allOn, notify_feedback: false })
    await store.setCategory('notify_feedback', false)

    expect(fetchMock).toHaveBeenLastCalledWith('/notifications/settings', {
      method: 'PATCH',
      body: { notify_feedback: false },
    })
    expect(store.settings).toEqual({ ...allOn, notify_feedback: false })
  })

  it('rolls the toggle back when the request fails', async () => {
    fetchMock.mockResolvedValueOnce(allOn)
    const { store } = await loadStore()
    await store.fetchSettings()

    fetchMock.mockRejectedValueOnce(new Error('offline'))
    await store.setCategory('notify_content', false)

    expect(store.settings).toEqual(allOn)
    expect(store.error).toBeTruthy()
    expect(store.saving).toBeNull()
  })

  it('ignores a toggle before settings are loaded', async () => {
    const { store } = await loadStore()

    await store.setCategory('notify_content', false)

    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('exposes one labelled category per settings key', async () => {
    const { categories } = await loadStore()

    expect(categories.map((c) => c.key).sort()).toEqual(Object.keys(allOn).sort())
    expect(categories.every((c) => c.label && c.hint)).toBe(true)
  })
})
