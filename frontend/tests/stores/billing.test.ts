/**
 * Billing store: balance/plans parsing and the YooKassa payment actions.
 *
 * Follows the useApi.probe.test.ts pattern: vi.resetModules() + dynamic import
 * so each test gets a fresh module graph. The store relies on Nuxt auto-imports
 * (useApi, ref, computed) — those are stubbed as globals. Pinia is imported
 * dynamically AFTER resetModules so the store and the test share the same
 * (fresh) pinia module instance.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref, computed } from 'vue'

const fetchMock = vi.fn()

const loadStore = async () => {
  const { createPinia, setActivePinia } = await import('pinia')
  setActivePinia(createPinia())
  const { useBillingStore } = await import('../../src/stores/billing')
  return useBillingStore()
}

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

describe('useBillingStore', () => {
  it('fetchBalance кладёт balance, available считается из него', async () => {
    fetchMock.mockResolvedValue({ balance: 100, reserved: 30, available: 70, plan: 'pro' })

    const store = await loadStore()
    await store.fetchBalance()

    expect(fetchMock).toHaveBeenCalledWith('/billing/balance')
    expect(store.balance).toEqual({ balance: 100, reserved: 30, available: 70, plan: 'pro' })
    expect(store.available).toBe(70)
    expect(store.reserved).toBe(30)
    expect(store.total).toBe(100)
    expect(store.currentPlan).toBe('pro')
  })

  it('createPayment возвращает {payment_id, confirmation_url} и не пишет error', async () => {
    fetchMock.mockResolvedValue({
      payment_id: 'pay-1',
      confirmation_url: 'https://yookassa.test/confirm',
    })

    const store = await loadStore()
    const result = await store.createPayment('pack_50')

    expect(fetchMock).toHaveBeenCalledWith('/billing/payments', {
      method: 'POST',
      body: { package_key: 'pack_50' },
    })
    expect(result).toEqual({
      payment_id: 'pay-1',
      confirmation_url: 'https://yookassa.test/confirm',
    })
    expect(store.error).toBeNull()
  })

  it('createPayment при ошибке возвращает null и пишет error', async () => {
    fetchMock.mockRejectedValue({ data: { detail: 'Платежи временно недоступны' } })

    const store = await loadStore()
    const result = await store.createPayment('pack_50')

    expect(result).toBeNull()
    expect(store.error).toBe('Платежи временно недоступны')
  })

  it('fetchPlans парсит packages (вместо topup_packs)', async () => {
    fetchMock.mockResolvedValue({
      weights: { vision_analyze: 3, quiz_generate: 2 },
      plans: { free: { monthly_allowance: 0, onetime_credits: 10, price_rub: 0 } },
      packages: {
        pack_50: { credits: 50, price_rub: 490 },
        pack_200: { credits: 200, price_rub: 1690 },
      },
    })

    const store = await loadStore()
    await store.fetchPlans()

    expect(fetchMock).toHaveBeenCalledWith('/billing/plans')
    expect(store.packages).toEqual({
      pack_50: { credits: 50, price_rub: 490 },
      pack_200: { credits: 200, price_rub: 1690 },
    })
    expect(store.weights).toEqual({ vision_analyze: 3, quiz_generate: 2 })
    expect(store.plans.free).toEqual({ monthly_allowance: 0, onetime_credits: 10, price_rub: 0 })
  })

  it('fetchPayment возвращает платёж', async () => {
    const payment = {
      id: 'pay-1',
      package_key: 'pack_50',
      amount_rub: '490.00',
      credits: 50,
      status: 'succeeded',
      created_at: '2026-06-11T10:00:00Z',
    }
    fetchMock.mockResolvedValue(payment)

    const store = await loadStore()
    const result = await store.fetchPayment('pay-1')

    expect(fetchMock).toHaveBeenCalledWith('/billing/payments/pay-1')
    expect(result).toEqual(payment)
  })
})
