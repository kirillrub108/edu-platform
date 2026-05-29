<script setup lang="ts">
import {
  Coins,
  Wallet,
  Lock,
  TrendingUp,
  Sparkles,
  History,
  AlertCircle,
  Check,
  RefreshCw,
  Info,
} from 'lucide-vue-next'
import {
  COST_LABELS,
  PLAN_META,
  PLAN_ORDER,
  operationLabel,
  planLabel,
  formatRub,
  formatDateTime,
} from '~/composables/useBillingMeta'

definePageMeta({ middleware: ['auth', 'teacher'], layout: 'bare' })

const billing = useBillingStore()
const {
  balance,
  transactions,
  weights,
  plans,
  topupPacks,
  loadingBalance,
  loadingTx,
  available,
  reserved,
  total,
  currentPlan,
} = storeToRefs(billing)

onMounted(async () => {
  await Promise.all([billing.fetchBalance(), billing.fetchPlans(), billing.fetchTransactions()])
  await restoreScroll()
})

const ACCENTS: Record<string, { ring: string; chip: string; price: string }> = {
  gray: { ring: 'ring-gray-300', chip: 'bg-gray-100 text-gray-700', price: 'text-gray-900' },
  violet: { ring: 'ring-violet-400', chip: 'bg-violet-100 text-violet-700', price: 'text-violet-700' },
  fuchsia: { ring: 'ring-fuchsia-400', chip: 'bg-fuchsia-100 text-fuchsia-700', price: 'text-fuchsia-700' },
  indigo: { ring: 'ring-indigo-400', chip: 'bg-indigo-100 text-indigo-700', price: 'text-indigo-700' },
}
const accentFor = (plan: string) => ACCENTS[PLAN_META[plan]?.accent ?? 'gray']!

// CREDIT_WEIGHTS entries in a stable, readable order.
const costRows = computed(() =>
  Object.entries(weights.value)
    .map(([key, cost]) => ({ key, cost, label: COST_LABELS[key] ?? key }))
    .sort((a, b) => b.cost - a.cost),
)

const signed = (n: number) => (n > 0 ? `+${n}` : `${n}`)
</script>

<template>
  <div class="flex">
    <AppSidebar />
    <main class="flex-1 min-w-0 px-6 lg:px-10 py-8">
      <!-- Header -->
      <div class="mb-6">
        <div class="text-xs text-gray-500 mb-1 uppercase tracking-wide">Преподаватель</div>
        <h1 class="text-2xl font-semibold text-gray-900">Баланс и тарифы</h1>
      </div>

      <!-- Balance hero -->
      <section
        class="rounded-3xl bg-gradient-to-br from-violet-600 via-violet-600 to-purple-500 text-white p-6 lg:p-7 shadow-soft mb-6"
      >
        <div class="flex flex-wrap items-start justify-between gap-6">
          <div>
            <div class="text-sm opacity-80 inline-flex items-center gap-1.5">
              <Coins class="w-4 h-4" /> Доступно для генерации
            </div>
            <div class="mt-1 flex items-baseline gap-2">
              <span class="text-5xl font-semibold tabular-nums leading-none">
                {{ loadingBalance && balance === null ? '—' : available }}
              </span>
              <span class="text-lg opacity-70">кредитов</span>
            </div>
            <div class="mt-3 inline-flex items-center gap-2 text-xs bg-white/15 rounded-full px-3 py-1">
              <Sparkles class="w-3.5 h-3.5" />
              Тариф: <span class="font-semibold">{{ planLabel(currentPlan) }}</span>
            </div>
          </div>

          <!-- balance breakdown -->
          <div class="flex gap-3">
            <div class="rounded-2xl bg-white/10 px-4 py-3 min-w-[110px]">
              <div class="text-xs opacity-75 inline-flex items-center gap-1">
                <Wallet class="w-3.5 h-3.5" /> Всего
              </div>
              <div class="text-2xl font-semibold tabular-nums mt-0.5">{{ total }}</div>
            </div>
            <div class="rounded-2xl bg-white/10 px-4 py-3 min-w-[110px]">
              <div class="text-xs opacity-75 inline-flex items-center gap-1">
                <Lock class="w-3.5 h-3.5" /> В резерве
              </div>
              <div class="text-2xl font-semibold tabular-nums mt-0.5">{{ reserved }}</div>
            </div>
          </div>
        </div>
        <p class="mt-4 text-xs opacity-70 inline-flex items-center gap-1.5">
          <Info class="w-3.5 h-3.5 shrink-0" />
          Кредиты резервируются на время генерации и списываются после её успешного завершения.
        </p>
      </section>

      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <!-- LEFT: plans + packs + history -->
        <div class="lg:col-span-2 space-y-6">
          <!-- Plans -->
          <section>
            <h2 class="text-base font-semibold text-gray-900 mb-3">Тарифы</h2>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div
                v-for="plan in PLAN_ORDER"
                :key="plan"
                class="bg-white rounded-2xl border border-gray-100 p-5 shadow-soft flex flex-col"
                :class="plan === currentPlan ? ['ring-2', accentFor(plan).ring] : ''"
              >
                <div class="flex items-center justify-between">
                  <div>
                    <div class="text-base font-semibold text-gray-900">{{ planLabel(plan) }}</div>
                    <div class="text-xs text-gray-500">{{ PLAN_META[plan]?.tagline }}</div>
                  </div>
                  <span
                    v-if="plan === currentPlan"
                    class="text-[10px] uppercase tracking-wide rounded-full px-2 py-0.5"
                    :class="accentFor(plan).chip"
                  >
                    Текущий
                  </span>
                </div>

                <div class="mt-4 flex items-baseline gap-1">
                  <span class="text-2xl font-semibold tabular-nums" :class="accentFor(plan).price">
                    {{ plans[plan]?.price_rub ? formatRub(plans[plan]?.price_rub) : 'Бесплатно' }}
                  </span>
                  <span v-if="plans[plan]?.price_rub" class="text-xs text-gray-400">/ мес</span>
                </div>

                <ul class="mt-3 space-y-1.5 text-sm text-gray-600 flex-1">
                  <li v-if="plans[plan]?.monthly_allowance" class="flex items-center gap-2">
                    <Check class="w-4 h-4 text-emerald-500 shrink-0" />
                    {{ plans[plan]?.monthly_allowance }} кредитов в месяц
                  </li>
                  <li v-if="plans[plan]?.onetime_credits" class="flex items-center gap-2">
                    <Check class="w-4 h-4 text-emerald-500 shrink-0" />
                    {{ plans[plan]?.onetime_credits }} кредитов при старте
                  </li>
                  <li
                    v-if="!plans[plan]?.monthly_allowance && !plans[plan]?.onetime_credits"
                    class="flex items-center gap-2 text-gray-400"
                  >
                    <Check class="w-4 h-4 shrink-0" /> Базовые возможности
                  </li>
                </ul>

                <UiButton
                  v-if="plan !== currentPlan"
                  variant="secondary"
                  size="sm"
                  block
                  disabled
                  class="mt-4"
                >
                  Выбрать
                </UiButton>
                <div
                  v-else
                  class="mt-4 text-center text-xs text-gray-400 py-2"
                >
                  Активен
                </div>
              </div>
            </div>
          </section>

          <!-- Top-up packs -->
          <section>
            <h2 class="text-base font-semibold text-gray-900 mb-1">Разовое пополнение</h2>
            <p class="text-xs text-gray-500 mb-3">
              Докупите кредиты сверх тарифа — они не сгорают при продлении.
            </p>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div
                v-for="pack in topupPacks"
                :key="pack.credits"
                class="bg-white rounded-2xl border border-gray-100 p-5 shadow-soft flex items-center justify-between gap-4"
              >
                <div>
                  <div class="text-xl font-semibold tabular-nums text-gray-900 inline-flex items-center gap-1.5">
                    <Coins class="w-4 h-4 text-violet-500" /> {{ pack.credits }} кр.
                  </div>
                  <div class="text-sm text-gray-500 mt-0.5">{{ formatRub(pack.price_rub) }}</div>
                </div>
                <UiButton variant="secondary" size="sm" disabled>Купить</UiButton>
              </div>
            </div>
          </section>

          <!-- Transaction history -->
          <section>
            <div class="flex items-center justify-between mb-3">
              <h2 class="text-base font-semibold text-gray-900 inline-flex items-center gap-2">
                <History class="w-4 h-4 text-gray-400" /> История операций
              </h2>
              <button
                class="text-xs text-violet-700 hover:text-violet-800 inline-flex items-center gap-1 transition"
                :disabled="loadingTx"
                @click="billing.refresh()"
              >
                <RefreshCw class="w-3.5 h-3.5" :class="loadingTx ? 'animate-spin' : ''" />
                Обновить
              </button>
            </div>

            <div class="bg-white rounded-2xl border border-gray-100 shadow-soft overflow-hidden">
              <div v-if="loadingTx && !transactions.length" class="p-6 text-sm text-gray-500">
                Загрузка…
              </div>
              <div
                v-else-if="!transactions.length"
                class="p-8 text-center text-sm text-gray-500"
              >
                <History class="w-8 h-8 text-gray-300 mx-auto mb-2" />
                Операций пока нет.
              </div>
              <ul v-else class="divide-y divide-gray-50">
                <li
                  v-for="tx in transactions"
                  :key="tx.id"
                  class="flex items-center gap-3 px-5 py-3"
                >
                  <span
                    class="w-2 h-2 rounded-full shrink-0"
                    :class="tx.delta > 0 ? 'bg-emerald-500' : 'bg-rose-400'"
                  />
                  <div class="min-w-0 flex-1">
                    <div class="text-sm font-medium text-gray-800 truncate">
                      {{ operationLabel(tx.operation) }}
                    </div>
                    <div class="text-xs text-gray-400 truncate">
                      {{ formatDateTime(tx.created_at) }}
                      <template v-if="tx.description"> · {{ tx.description }}</template>
                    </div>
                  </div>
                  <span
                    class="text-sm font-semibold tabular-nums shrink-0"
                    :class="tx.delta > 0 ? 'text-emerald-600' : 'text-rose-500'"
                  >
                    {{ signed(tx.delta) }}
                  </span>
                </li>
              </ul>
            </div>
          </section>
        </div>

        <!-- RIGHT: cost table -->
        <aside class="lg:col-span-1">
          <div class="bg-white rounded-2xl border border-gray-100 p-5 shadow-soft lg:sticky lg:top-24">
            <h2 class="text-base font-semibold text-gray-900 inline-flex items-center gap-2 mb-1">
              <TrendingUp class="w-4 h-4 text-gray-400" /> Стоимость операций
            </h2>
            <p class="text-xs text-gray-500 mb-4">Сколько кредитов списывается за каждое действие.</p>

            <ul class="space-y-2.5">
              <li
                v-for="row in costRows"
                :key="row.key"
                class="flex items-center justify-between gap-3"
              >
                <span class="text-sm text-gray-600">{{ row.label }}</span>
                <span
                  class="text-xs font-semibold tabular-nums rounded-full px-2 py-0.5 shrink-0"
                  :class="row.cost === 0 ? 'bg-emerald-100 text-emerald-700' : 'bg-violet-100 text-violet-700'"
                >
                  {{ row.cost === 0 ? 'бесплатно' : `${row.cost} кр.` }}
                </span>
              </li>
            </ul>

            <div
              class="mt-5 flex items-start gap-2 text-xs text-gray-500 bg-gray-50 border border-gray-100 rounded-xl p-3"
            >
              <AlertCircle class="w-4 h-4 shrink-0 mt-0.5 text-gray-400" />
              <span>
                Онлайн-оплата подключается отдельно. Сейчас баланс пополняется администратором —
                напишите в поддержку.
              </span>
            </div>
          </div>
        </aside>
      </div>
    </main>
  </div>
</template>
