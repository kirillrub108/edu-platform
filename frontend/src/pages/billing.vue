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
  operationLabel,
  formatRub,
  formatDateTime,
} from '~/composables/useBillingMeta'

definePageMeta({ middleware: ['auth', 'teacher'], layout: 'bare' })

const billing = useBillingStore()
const {
  balance,
  transactions,
  weights,
  packages,
  videoPricing,
  payments,
  loadingBalance,
  loadingTx,
  loadingPayments,
  available,
  reserved,
  total,
} = storeToRefs(billing)

const route = useRoute()

// ── Buying a credit package ────────────────────────────────────────────────────

const packs = computed(() =>
  Object.entries(packages.value)
    .map(([key, p]) => ({ key, ...p }))
    .sort((a, b) => a.credits - b.credits),
)

const buyingKey = ref<string | null>(null)
const payError = ref('')
// Mandatory consent before any purchase can be initiated.
const acceptedPurchaseTerms = ref(false)

const buyPack = async (key: string) => {
  if (buyingKey.value || !acceptedPurchaseTerms.value) return
  buyingKey.value = key
  payError.value = ''
  const r = await billing.createPayment(key)
  if (r) {
    // Keep the loading state — we're leaving for the YooKassa checkout page.
    window.location.href = r.confirmation_url
    return
  }
  payError.value = billing.error ?? 'Не удалось создать платёж'
  buyingKey.value = null
}

// ── Return from YooKassa (?payment_id=...) ─────────────────────────────────────

const paymentBanner = ref<{ kind: 'success' | 'fail' | 'pending'; text: string } | null>(null)
let pollStopped = false

const handlePaymentReturn = async () => {
  const pid = route.query.payment_id
  const paymentId = Array.isArray(pid) ? pid[0] : pid
  if (!paymentId) return

  // Poll every 2s for up to 60s — the GET itself pulls the status from YooKassa.
  const startedAt = Date.now()
  let payment = await billing.fetchPayment(paymentId)
  while (!pollStopped && payment?.status === 'pending' && Date.now() - startedAt < 60_000) {
    await new Promise(resolve => setTimeout(resolve, 2000))
    payment = await billing.fetchPayment(paymentId)
  }
  if (pollStopped) return

  if (payment?.status === 'succeeded') {
    paymentBanner.value = { kind: 'success', text: `Кредиты зачислены: +${payment.credits} CR` }
  } else if (payment?.status === 'canceled') {
    paymentBanner.value = { kind: 'fail', text: 'Платёж не прошёл' }
  } else {
    paymentBanner.value = {
      kind: 'pending',
      text: 'Платёж обрабатывается, кредиты появятся после подтверждения',
    }
  }

  await billing.refresh()
  void billing.fetchPayments()
  // Drop ?payment_id so a page refresh doesn't restart the polling.
  await navigateTo('/billing', { replace: true })
}

onMounted(async () => {
  await Promise.all([
    billing.fetchBalance(),
    billing.fetchPlans(),
    billing.fetchTransactions(),
    billing.fetchPayments(),
  ])
  await restoreScroll()
  void handlePaymentReturn()
})

onUnmounted(() => { pollStopped = true })

const PAYMENT_STATUS_META: Record<string, { label: string; chip: string }> = {
  pending: { label: 'В обработке', chip: 'bg-amber-100 text-amber-700' },
  succeeded: { label: 'Оплачен', chip: 'bg-emerald-100 text-emerald-700' },
  canceled: { label: 'Отменён', chip: 'bg-gray-100 text-gray-500' },
}

// CREDIT_WEIGHTS entries in a stable, readable order.
const costRows = computed(() =>
  Object.entries(weights.value)
    .map(([key, cost]) => ({ key, cost, label: COST_LABELS[key] ?? key }))
    .sort((a, b) => b.cost - a.cost),
)

// ── Lifetime trial ─────────────────────────────────────────────────────────────
const trial = computed(() => balance.value?.trial ?? null)
const trialExhausted = computed(() => {
  const t = trial.value
  return (
    !!t &&
    t.lectures_used >= t.lectures_limit &&
    t.quizzes_used >= t.quizzes_limit
  )
})
// A paying user no longer needs the trial highlighted — render it muted.
const hasPurchases = computed(() => payments.value.some(p => p.status === 'succeeded'))

const scrollToPacks = () => {
  document.getElementById('packs')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

// ── Video cost examples computed from the backend formula params ────────────────
// Range = text-mode (lower base) … auto-mode (higher base) for the same slide
// count, using the auto narration norm for the per-character term.
const videoExamples = computed(() => {
  const vp = videoPricing.value
  if (!vp) return []
  return [10, 20].map((slides) => {
    const tts = Math.ceil((slides * vp.auto_chars_per_slide) / vp.chars_per_credit)
    return {
      slides,
      lo: vp.text_base + slides + tts,
      hi: vp.auto_base + slides + tts,
    }
  })
})

const signed = (n: number) => (n > 0 ? `+${n}` : `${n}`)

// ── Top-up temporarily disabled — see docs/DECISIONS.md ────────────────────────
const GOOGLE_FORM_URL = 'https://docs.google.com/forms/d/e/1FAIpQLScoZQb5VAXVRV2XuWIBxZcdCIfJBPJ5Kujz9-hpxxVf3PoOag/viewform'
</script>

<template>
  <div class="flex">
    <AppSidebar />
    <main class="flex-1 min-w-0 px-6 lg:px-10 py-8">
      <!-- Header -->
      <div class="mb-6">
        <div class="text-xs text-gray-500 mb-1 uppercase tracking-wide">Преподаватель</div>
        <h1 class="text-2xl font-semibold text-gray-900">Баланс и кредиты</h1>
      </div>

      <!-- Payment result banner (return from YooKassa) -->
      <div
        v-if="paymentBanner"
        class="flex items-start gap-2 mb-6 text-sm rounded-2xl border px-4 py-3"
        :class="{
          'text-emerald-700 bg-emerald-50 border-emerald-200': paymentBanner.kind === 'success',
          'text-rose-700 bg-rose-50 border-rose-200': paymentBanner.kind === 'fail',
          'text-gray-600 bg-white border-gray-200': paymentBanner.kind === 'pending',
        }"
      >
        <Check v-if="paymentBanner.kind === 'success'" class="w-4 h-4 shrink-0 mt-0.5" />
        <AlertCircle v-else class="w-4 h-4 shrink-0 mt-0.5" />
        <span class="flex-1">{{ paymentBanner.text }}</span>
        <button
          type="button"
          class="shrink-0 opacity-60 hover:opacity-100 transition leading-none"
          aria-label="Закрыть"
          @click="paymentBanner = null"
        >✕</button>
      </div>

      <!-- Balance hero -->
      <section
        class="rounded-3xl bg-brand-gradient text-white p-6 lg:p-7 shadow-soft mb-6"
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
        <!-- LEFT: trial + packs + history -->
        <div class="lg:col-span-2 space-y-6">
          <!-- Lifetime free trial -->
          <section v-if="trial">
            <div
              class="rounded-2xl border p-5 shadow-soft"
              :class="hasPurchases
                ? 'bg-white border-gray-100'
                : 'bg-violet-50/60 border-violet-100'"
            >
              <div class="flex items-center gap-2 mb-2">
                <Sparkles
                  class="w-4 h-4 shrink-0"
                  :class="hasPurchases ? 'text-gray-400' : 'text-violet-500'"
                />
                <h2 class="text-base font-semibold text-gray-900">Бесплатный триал</h2>
              </div>

              <template v-if="!trialExhausted">
                <p class="text-sm text-gray-700">
                  Лекции:
                  <span class="font-semibold tabular-nums">{{ trial.lectures_used }} из {{ trial.lectures_limit }}</span>
                  · Тесты:
                  <span class="font-semibold tabular-nums">{{ trial.quizzes_used }} из {{ trial.quizzes_limit }}</span>
                </p>
                <p class="text-xs text-gray-500 mt-1">
                  Доступен один раз — дальше операции оплачиваются кредитами.
                </p>
              </template>
              <template v-else>
                <p class="text-sm text-gray-600">Триал использован.</p>
                <button
                  type="button"
                  class="mt-2 text-sm font-medium text-violet-700 hover:text-violet-800 transition"
                  @click="scrollToPacks"
                >
                  Купить кредиты →
                </button>
              </template>
            </div>
          </section>

          <!-- Top-up packs (temporarily disabled — blurred behind an overlay, logic kept intact) -->
          <section id="packs" class="relative scroll-mt-24">
            <!-- Overlay -->
            <div
              class="absolute inset-0 z-10 flex items-center justify-center rounded-2xl bg-white/50 p-4"
            >
              <div class="bg-white rounded-2xl shadow-xl border border-gray-100 p-6 max-w-sm text-center space-y-3">
                <h3 class="text-base font-semibold text-gray-900">В разработке</h3>
                <p class="text-sm text-gray-500">
                  Если вам интересен данный продукт, напишите нам, и мы сможем предоставить вам
                  дополнительные генерации.
                </p>
                <a
                  :href="GOOGLE_FORM_URL"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="inline-flex items-center justify-center gap-2 text-sm font-medium px-5 py-2.5 rounded-xl
                         bg-brand-gradient text-white shadow-soft hover:shadow-soft-hover hover:brightness-110
                         active:brightness-95 active:scale-[0.97] transition-all duration-150 ease-out"
                >
                  Написать нам
                </a>
              </div>
            </div>

            <!-- Blurred content, non-interactive -->
            <div class="pointer-events-none select-none blur-sm">
            <h2 class="text-base font-semibold text-gray-900 mb-1">Разовое пополнение</h2>
            <p class="text-xs text-gray-500 mb-3">
              Кредиты не сгорают.
            </p>
            <div
              v-if="payError"
              class="flex items-start gap-2 mb-3 text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-xl px-3 py-2"
            >
              <AlertCircle class="w-4 h-4 shrink-0 mt-0.5" />
              <span>{{ payError }}</span>
            </div>

            <!-- Legal docs + mandatory consent, shown before the pay buttons -->
            <div class="mb-4 rounded-2xl border border-gray-100 bg-white p-4 shadow-soft">
              <div class="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-gray-500">
                <NuxtLink
                  v-for="d in LEGAL_DOCUMENTS"
                  :key="d.key"
                  :to="d.route"
                  target="_blank"
                  class="hover:text-violet-700 hover:underline transition"
                >
                  {{ d.shortTitle }}
                </NuxtLink>
              </div>
              <label class="mt-3 flex items-start gap-2.5 text-xs leading-relaxed text-gray-600">
                <input
                  v-model="acceptedPurchaseTerms"
                  type="checkbox"
                  class="mt-0.5 h-4 w-4 shrink-0 rounded border-gray-300 text-violet-600 focus:ring-violet-500/30"
                />
                <span>
                  Оплачивая, я принимаю
                  <NuxtLink
                    :to="legalDoc('offer').route"
                    target="_blank"
                    class="font-medium text-violet-700 hover:underline"
                  >Публичную оферту</NuxtLink>,
                  <NuxtLink
                    :to="legalDoc('privacy').route"
                    target="_blank"
                    class="font-medium text-violet-700 hover:underline"
                  >Политику конфиденциальности</NuxtLink>
                  и
                  <NuxtLink
                    :to="legalDoc('refund').route"
                    target="_blank"
                    class="font-medium text-violet-700 hover:underline"
                  >Политику возврата</NuxtLink>
                </span>
              </label>
              <p v-if="!acceptedPurchaseTerms" class="mt-2 text-xs text-gray-400">
                Отметьте согласие, чтобы продолжить оплату.
              </p>
            </div>

            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div
                v-for="pack in packs"
                :key="pack.key"
                class="bg-white rounded-2xl border border-gray-100 p-5 shadow-soft flex items-center justify-between gap-4"
              >
                <div>
                  <div class="text-xl font-semibold tabular-nums text-gray-900 inline-flex items-center gap-1.5">
                    <Coins class="w-4 h-4 text-violet-500" /> {{ pack.credits }} кр.
                  </div>
                  <div class="text-sm text-gray-500 mt-0.5">{{ formatRub(pack.price_rub) }}</div>
                </div>
                <UiButton
                  variant="secondary"
                  size="sm"
                  :loading="buyingKey === pack.key"
                  :disabled="(!!buyingKey && buyingKey !== pack.key) || !acceptedPurchaseTerms"
                  @click="buyPack(pack.key)"
                >
                  Купить
                </UiButton>
              </div>
            </div>
            </div>
          </section>

          <!-- Payments history -->
          <section>
            <h2 class="text-base font-semibold text-gray-900 mb-3">Платежи</h2>
            <div class="bg-white rounded-2xl border border-gray-100 shadow-soft overflow-hidden">
              <div v-if="loadingPayments && !payments.length" class="p-6 text-sm text-gray-500">
                Загрузка…
              </div>
              <div v-else-if="!payments.length" class="p-6 text-sm text-gray-500">
                Платежей пока нет.
              </div>
              <ul v-else class="divide-y divide-gray-50">
                <li
                  v-for="p in payments"
                  :key="p.id"
                  class="flex items-center gap-3 px-5 py-3"
                >
                  <div class="min-w-0 flex-1">
                    <div class="text-sm font-medium text-gray-800">{{ p.credits }} кр.</div>
                    <div class="text-xs text-gray-500">{{ formatDateTime(p.created_at) }}</div>
                  </div>
                  <span class="text-sm text-gray-600 tabular-nums shrink-0">
                    {{ formatRub(Number(p.amount_rub)) }}
                  </span>
                  <span
                    class="text-xs rounded-full px-2 py-0.5 shrink-0"
                    :class="PAYMENT_STATUS_META[p.status]?.chip ?? 'bg-gray-100 text-gray-500'"
                  >
                    {{ PAYMENT_STATUS_META[p.status]?.label ?? p.status }}
                  </span>
                </li>
              </ul>
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
                    <div class="text-xs text-gray-500 truncate">
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

            <div
              v-if="videoPricing"
              class="text-xs text-gray-600 bg-violet-50/60 border border-violet-100 rounded-xl p-3 mb-4 space-y-1"
            >
              <div class="font-medium text-gray-700">Видеолекция</div>
              <div>
                Текст-режим: {{ videoPricing.text_base }} CR + 1 CR за слайд
                + 1 CR за каждые {{ videoPricing.chars_per_credit }} символов озвучки.
              </div>
              <div>
                Авто-режим: {{ videoPricing.auto_base }} CR + 1 CR за слайд
                (≈ {{ videoPricing.auto_chars_per_slide }} символов на слайд).
              </div>
              <div class="text-gray-500 pt-0.5">
                <template v-for="(ex, i) in videoExamples" :key="ex.slides">
                  <span v-if="i"> · </span>{{ ex.slides }} слайдов ≈ {{ ex.lo }}–{{ ex.hi }} CR
                </template>
              </div>
            </div>

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
          </div>
        </aside>
      </div>
    </main>
  </div>
</template>
