// Pricing data for the PUBLIC landing page.
//
// There are NO subscriptions — the product sells one-time credit packs and
// charges per AI-operation. This MIRRORS exactly what the authenticated tariffs
// page (pages/billing.vue) shows, which is driven by GET /api/v1/billing/plans.
// That endpoint requires auth and the landing is anonymous, so we mirror the
// backend values here. Keep in sync with backend/app/constants.py:
//   CREDIT_PACKAGES, CREDIT_WEIGHTS, VIDEO_TEXT_BASE_CREDITS,
//   VIDEO_AUTO_BASE_CREDITS, TTS_CHARS_PER_CREDIT, AUTO_CHARS_PER_SLIDE,
//   TRIAL_LECTURES, TRIAL_QUIZZES.
// Operation labels are reused from useBillingMeta so they can't drift.

import { COST_LABELS, formatRub } from './useBillingMeta'

export interface CreditPack {
  credits: number
  /** Formatted total price, e.g. "190 ₽". */
  price: string
  /** Formatted unit price, e.g. "3,8 ₽" — shows the bulk discount. */
  perCredit: string
}

export interface OperationCost {
  label: string
  cost: number
  free: boolean
}

export interface VideoExample {
  slides: number
  lo: number
  hi: number
}

export interface VideoPricing {
  textBase: number
  autoBase: number
  charsPerCredit: number
  autoCharsPerSlide: number
  examples: VideoExample[]
}

export interface CreditFact {
  title: string
  body: string
}

// CREDIT_PACKAGES (constants.py), sorted ascending like billing.vue.
const PACK_DATA: [credits: number, priceRub: number][] = [
  [50, 190],
  [200, 590],
  [500, 1290],
  [1200, 2690],
]

function perCreditLabel(priceRub: number, credits: number): string {
  const v = Math.round((priceRub / credits) * 10) / 10
  return `${v.toFixed(1).replace('.', ',')} ₽`
}

const PACKS: CreditPack[] = PACK_DATA.map(([credits, priceRub]) => ({
  credits,
  price: formatRub(priceRub),
  perCredit: perCreditLabel(priceRub, credits),
}))

// CREDIT_WEIGHTS, ordered by cost desc to match the billing.vue cost table.
const OPERATION_COSTS: OperationCost[] = [
  { label: COST_LABELS.vision_analyze, cost: 5, free: false },
  { label: COST_LABELS.quiz_generate, cost: 5, free: false },
  { label: COST_LABELS.ai_review, cost: 2, free: false },
  { label: COST_LABELS.slide_regen, cost: 1, free: false },
  { label: COST_LABELS.quiz_grade, cost: 0, free: true },
]

// Video formula params (constants.py). Examples mirror billing.vue's range:
// text-mode base (lo) … auto-mode base (hi) for the same slide count.
const VIDEO_TEXT_BASE = 2
const VIDEO_AUTO_BASE = 3
const CHARS_PER_CREDIT = 3000
const AUTO_CHARS_PER_SLIDE = 600

const VIDEO_PRICING: VideoPricing = {
  textBase: VIDEO_TEXT_BASE,
  autoBase: VIDEO_AUTO_BASE,
  charsPerCredit: CHARS_PER_CREDIT,
  autoCharsPerSlide: AUTO_CHARS_PER_SLIDE,
  examples: [10, 20].map((slides) => {
    const tts = Math.ceil((slides * AUTO_CHARS_PER_SLIDE) / CHARS_PER_CREDIT)
    return { slides, lo: VIDEO_TEXT_BASE + slides + tts, hi: VIDEO_AUTO_BASE + slides + tts }
  }),
}

// TRIAL_LECTURES / TRIAL_QUIZZES.
const TRIAL = { lectures: 2, quizzes: 2 }

// Mechanics, matching what billing.vue tells the user. TTS_CHARS_PER_CREDIT
// anchors "что такое 1 кредит"; "не сгорают" is the real policy (no carryover,
// since there are no subscriptions).
const CREDIT_FACTS: CreditFact[] = [
  {
    title: '1 кредит — единица ИИ-работы',
    body: 'Примерно озвучка 3000 знаков текста или обработка одного слайда. Кредиты тратятся только на ИИ-операции.',
  },
  {
    title: 'Резерв → списание по факту',
    body: 'Кредиты резервируются на время генерации и списываются после её успешного завершения — излишек резерва возвращается на баланс.',
  },
  {
    title: 'Кредиты не сгорают',
    body: 'Никаких подписок: покупаете кредиты разово, остаток сохраняется. Старт — бесплатный триал на 2 лекции и 2 теста.',
  },
]

export function useLandingPricing() {
  return {
    packs: PACKS,
    operationCosts: OPERATION_COSTS,
    videoPricing: VIDEO_PRICING,
    creditFacts: CREDIT_FACTS,
    trial: TRIAL,
  }
}
