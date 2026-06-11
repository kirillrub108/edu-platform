import { defineStore } from 'pinia'

export interface TrialState {
  lectures_used: number
  lectures_limit: number
  quizzes_used: number
  quizzes_limit: number
}

export interface BalanceState {
  balance: number
  reserved: number
  available: number
  plan: string
  trial?: TrialState | null
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

export interface CreditPackage {
  credits: number
  price_rub: number
}

export interface VideoPricing {
  text_base: number
  auto_base: number
  chars_per_credit: number
  auto_chars_per_slide: number
}

export interface PaymentInfo {
  id: string
  package_key: string
  amount_rub: string
  credits: number
  status: 'pending' | 'succeeded' | 'canceled'
  created_at: string
}

interface PlansResponse {
  weights: Record<string, number>
  plans: Record<string, PlanConfig>
  packages: Record<string, CreditPackage>
  video_pricing: VideoPricing
}

export const useBillingStore = defineStore('billing', () => {
  const { apiFetch } = useApi()

  const balance = ref<BalanceState | null>(null)
  const transactions = ref<Transaction[]>([])
  const weights = ref<Record<string, number>>({})
  const plans = ref<Record<string, PlanConfig>>({})
  const packages = ref<Record<string, CreditPackage>>({})
  const videoPricing = ref<VideoPricing | null>(null)
  const payments = ref<PaymentInfo[]>([])

  const loadingBalance = ref(false)
  const loadingTx = ref(false)
  const loadingPlans = ref(false)
  const loadingPayments = ref(false)
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
      packages.value = res.packages
      videoPricing.value = res.video_pricing
    } catch (e: any) {
      error.value = e?.data?.detail ?? 'Не удалось загрузить данные о ценах'
    } finally {
      loadingPlans.value = false
    }
  }

  // Creates a YooKassa payment; the caller redirects to confirmation_url.
  const createPayment = async (
    packageKey: string,
  ): Promise<{ payment_id: string; confirmation_url: string } | null> => {
    try {
      return await apiFetch<{ payment_id: string; confirmation_url: string }>(
        '/billing/payments',
        { method: 'POST', body: { package_key: packageKey } },
      )
    } catch (e: any) {
      error.value = e?.data?.detail ?? 'Не удалось создать платёж'
      return null
    }
  }

  // Polling this endpoint also pulls the latest status from YooKassa.
  const fetchPayment = async (id: string): Promise<PaymentInfo | null> => {
    try {
      return await apiFetch<PaymentInfo>(`/billing/payments/${id}`)
    } catch {
      return null
    }
  }

  const fetchPayments = async () => {
    loadingPayments.value = true
    try {
      payments.value = await apiFetch<PaymentInfo[]>('/billing/payments')
    } catch (e: any) {
      error.value = e?.data?.detail ?? 'Не удалось загрузить историю платежей'
    } finally {
      loadingPayments.value = false
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
    packages,
    videoPricing,
    payments,
    loadingBalance,
    loadingTx,
    loadingPlans,
    loadingPayments,
    error,
    available,
    reserved,
    total,
    currentPlan,
    fetchBalance,
    fetchTransactions,
    fetchPlans,
    createPayment,
    fetchPayment,
    fetchPayments,
    refresh,
  }
})
