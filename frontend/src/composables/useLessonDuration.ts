// Mirrors backend app/constants.py (DETAIL_LEVEL_BODY_WORDS, WORDS_PER_MINUTE,
// EDGE_SLIDE_BUDGET_WEIGHT) and app/services/duration_service.py. Keep the two
// in sync — the backend is the one that actually budgets the narration prompt.
export const WORDS_PER_MINUTE = 130

export const DetailLevel = {
  BRIEF: 'brief',
  AUTO: 'auto',
  HIGH: 'high',
} as const

export type DetailLevelValue = typeof DetailLevel[keyof typeof DetailLevel]

export const DEFAULT_DETAIL_LEVEL: DetailLevelValue = DetailLevel.AUTO

/** Word budget for one body slide at each level. */
const DETAIL_LEVEL_BODY_WORDS: Record<DetailLevelValue, number> = {
  [DetailLevel.BRIEF]: 120,
  [DetailLevel.AUTO]: 225,
  [DetailLevel.HIGH]: 400,
}

const EDGE_SLIDE_BUDGET_WEIGHT = 0.4

function bodyWords(level: DetailLevelValue | null): number {
  return DETAIL_LEVEL_BODY_WORDS[level ?? DEFAULT_DETAIL_LEVEL]
    ?? DETAIL_LEVEL_BODY_WORDS[DEFAULT_DETAIL_LEVEL]
}

export interface DetailLevelOption {
  value: DetailLevelValue
  label: string
  hint: string
}

/** Auto mode: the LLM writes the narration from scratch. */
export const DETAIL_LEVEL_OPTIONS: DetailLevelOption[] = [
  { value: DetailLevel.BRIEF, label: 'Кратко', hint: 'Тезисно, только суть каждого слайда' },
  { value: DetailLevel.AUTO, label: 'Авто', hint: 'Обычное объяснение — подходит большинству' },
  { value: DetailLevel.HIGH, label: 'Подробно', hint: 'Максимальное раскрытие: примеры, контекст' },
]

/** Manual mode: the same levels act on the text the teacher already wrote. */
export const DETAIL_LEVEL_OPTIONS_MANUAL: DetailLevelOption[] = [
  { value: DetailLevel.BRIEF, label: 'Кратко', hint: 'Сжать ваш текст до главной сути' },
  { value: DetailLevel.AUTO, label: 'Как есть', hint: 'Озвучить ваш текст дословно' },
  { value: DetailLevel.HIGH, label: 'Подробно', hint: 'Дополнить ваш текст пояснениями и примерами' },
]

/** How much narration a level asks for, relative to the default one. */
export function detailRatio(level: DetailLevelValue | null): number {
  return bodyWords(level) / DETAIL_LEVEL_BODY_WORDS[DEFAULT_DETAIL_LEVEL]
}

export function countWords(text: string): number {
  return text.split(/\s+/).filter(Boolean).length
}

export function estimateDurationSec(wordCount: number): number {
  return Math.round((wordCount / WORDS_PER_MINUTE) * 60)
}

/** m:ss — used for per-slide and whole-lesson estimates alike. */
export function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function slideWeights(slideCount: number): number[] {
  const weights = Array<number>(slideCount).fill(1)
  if (slideCount > 2) {
    weights[0] = EDGE_SLIDE_BUDGET_WEIGHT
    weights[slideCount - 1] = EDGE_SLIDE_BUDGET_WEIGHT
  }
  return weights
}

/**
 * Per-slide word allowances the backend will put into the narration prompts.
 * Title and closing slides get a smaller share than body slides.
 */
export function slideWordBudgets(
  level: DetailLevelValue | null,
  slideCount: number,
): number[] | null {
  if (slideCount <= 0) return null
  const perBody = bodyWords(level)
  return slideWeights(slideCount).map(w => Math.max(1, Math.round(perBody * w)))
}

/** Approximate lesson length for this deck at this level of detail. */
export function expectedDurationSec(level: DetailLevelValue | null, slideCount: number): number {
  const budgets = slideWordBudgets(level, slideCount)
  if (!budgets) return 0
  return estimateDurationSec(budgets.reduce((a, b) => a + b, 0))
}

/** "≈ 12 мин" — the label shown next to the detail-level choice. */
export function expectedDurationLabel(
  level: DetailLevelValue | null,
  slideCount: number,
): string | null {
  if (slideCount <= 0) return null
  const minutes = expectedDurationSec(level, slideCount) / 60
  return minutes < 1 ? '≈ 1 мин' : `≈ ${Math.round(minutes)} мин`
}
