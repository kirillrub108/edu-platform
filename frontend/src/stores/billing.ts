import { defineStore } from 'pinia'

export interface BalanceState {
  balance: number
  reserved: number
  available: number
  plan: string
}

export interface Transaction {
  id: string
  delta: number
  operation: string
  ref_id: string | null
  description: string | null
  created_at: string
}

export interface PlanConfig {
  monthly_allowance: number
  onetime_credits: number
  price_rub: number
}

export interface TopupPack {
  credits: number
  price_rub: number
}

interface PlansResponse {
  weights: Record<string, number>
  plans: Record<string, PlanConfig>
  topup_packs: TopupPack[]
}

export const useBillingStore = defineStore('billing', () => {
  const { apiFetch } = useApi()

  const balance = ref<BalanceState | null>(null)
  const transactions = ref<Transaction[]>([])
  const weights = ref<Record<string, number>>({})
  const plans = ref<Record<string, PlanConfig>>({})
  const topupPacks = ref<TopupPack[]>([])

  const loadingBalance = ref(false)
  const loadingTx = ref(false)
  const loadingPlans = ref(false)
  const error = ref<string | null>(null)

  const available = computed(() => balance.value?.available ?? 0)
  const reserved = computed(() => balance.value?.reserved ?? 0)
  const total = computed(() => balance.value?.balance ?? 0)
  const currentPlan = computed(() => balance.value?.plan ?? 'free')

  const fetchBalance = async () => {
    loadingBalance.value = true
    try {
      balance.value = await apiFetch<BalanceState>('/billing/balance')
    } catch (e: any) {
      error.value = e?.data?.detail ?? 'Не удалось загрузить баланс'
    } finally {
      loadingBalance.value = false
    }
  }

  const fetchTransactions = async (limit = 50) => {
    loadingTx.value = true
    try {
      transactions.value = await apiFetch<Transaction[]>(`/billing/transactions?limit=${limit}`)
    } catch (e: any) {
      error.value = e?.data?.detail ?? 'Не удалось загрузить историю операций'
    } finally {
      loadingTx.value = false
    }
  }

  // Plans/weights are static config — fetch once and cache.
  const fetchPlans = async () => {
    if (Object.keys(plans.value).length) return
    loadingPlans.value = true
    try {
      const res = await apiFetch<PlansResponse>('/billing/plans')
      weights.value = res.weights
      plans.value = res.plans
      topupPacks.value = res.topup_packs
    } catch (e: any) {
      error.value = e?.data?.detail ?? 'Не удалось загрузить тарифы'
    } finally {
      loadingPlans.value = false
    }
  }

  // Lightweight refresh after a credit-consuming action completes.
  const refresh = async () => {
    await Promise.all([fetchBalance(), fetchTransactions()])
  }

  return {
    balance,
    transactions,
    weights,
    plans,
    topupPacks,
    loadingBalance,
    loadingTx,
    loadingPlans,
    error,
    available,
    reserved,
    total,
    currentPlan,
    fetchBalance,
    fetchTransactions,
    fetchPlans,
    refresh,
  }
})
