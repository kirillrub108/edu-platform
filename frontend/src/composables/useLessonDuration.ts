// Mirrors backend app/constants.py (WORDS_PER_MINUTE, LESSON_DURATION_*,
// EDGE_SLIDE_BUDGET_WEIGHT) and app/services/duration_service.py. Keep the two
// in sync — the backend is the one that actually budgets the narration prompt.
export const WORDS_PER_MINUTE = 130

export const LESSON_DURATION_MIN_MINUTES = 1
export const LESSON_DURATION_MAX_MINUTES = 180

/** Quick picks next to the free-form minutes input. */
export const LESSON_DURATION_PRESETS_MIN = [5, 10, 15, 20, 30] as const

const EDGE_SLIDE_BUDGET_WEIGHT = 0.4

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

/**
 * Per-slide word allowances the backend will put into the narration prompts.
 * Title and closing slides get a smaller share than body slides.
 */
export function slideWordBudgets(targetMin: number | null, slideCount: number): number[] | null {
  if (targetMin === null || slideCount <= 0) return null

  const weights = Array<number>(slideCount).fill(1)
  if (slideCount > 2) {
    weights[0] = EDGE_SLIDE_BUDGET_WEIGHT
    weights[slideCount - 1] = EDGE_SLIDE_BUDGET_WEIGHT
  }

  const totalWords = targetMin * WORDS_PER_MINUTE
  const weightSum = weights.reduce((a, b) => a + b, 0)
  return weights.map(w => Math.max(1, Math.round((totalWords * w) / weightSum)))
}

/** Clamp free-form input to the range the backend accepts; null = auto. */
export function clampTargetDuration(value: number | null): number | null {
  if (value === null || !Number.isFinite(value)) return null
  const rounded = Math.round(value)
  if (rounded < LESSON_DURATION_MIN_MINUTES) return LESSON_DURATION_MIN_MINUTES
  if (rounded > LESSON_DURATION_MAX_MINUTES) return LESSON_DURATION_MAX_MINUTES
  return rounded
}
