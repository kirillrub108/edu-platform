/**
 * Logic behind the "Настройки генерации" dialog: the per-type counts replaced
 * the old "total + type checkboxes" model, so what needs pinning is the total,
 * the clamping of raw input, and exactly when "Сгенерировать" stays disabled.
 * Pure functions — no component mounting (no @vue/test-utils here).
 */

import { describe, expect, it } from 'vitest'
import {
  clampTypeCount,
  generationCountsError,
  totalRequestedQuestions,
} from '~/composables/useQuizAuthoring'
import type { QuizGenerationOptions, QuizTypeCount } from '~/composables/useQuizAuthoring'

// Mirrors what GET /quiz/generation-options serves from constants.py.
const limits: QuizGenerationOptions = {
  types: [
    { type: 'single_choice', default_count: 3 },
    { type: 'multiple_choice', default_count: 1 },
    { type: 'true_false', default_count: 1 },
    { type: 'short_answer', default_count: 0 },
  ],
  min_per_type: 0,
  max_per_type: 10,
  min_total: 1,
  max_total: 20,
  num_options: 4,
}

const counts = (...values: number[]): QuizTypeCount[] =>
  limits.types.map((t, i) => ({ type: t.type, count: values[i] ?? 0 }))

describe('totalRequestedQuestions', () => {
  it('sums every type, including the excluded ones', () => {
    expect(totalRequestedQuestions(counts(3, 1, 1, 0))).toBe(5)
  })

  it('is 0 for an all-zero request', () => {
    expect(totalRequestedQuestions(counts(0, 0, 0, 0))).toBe(0)
  })
})

describe('clampTypeCount', () => {
  it('rounds fractional input to a whole question', () => {
    expect(clampTypeCount(2.6, limits)).toBe(3)
  })

  it('clamps below the floor and above the ceiling', () => {
    expect(clampTypeCount(-4, limits)).toBe(limits.min_per_type)
    expect(clampTypeCount(99, limits)).toBe(limits.max_per_type)
  })

  it('falls back to the floor for a cleared / non-numeric field', () => {
    expect(clampTypeCount(Number.NaN, limits)).toBe(limits.min_per_type)
  })
})

describe('generationCountsError — drives the disabled state of "Сгенерировать"', () => {
  it('passes a valid mix', () => {
    expect(generationCountsError(counts(3, 1, 1, 0), limits)).toBeNull()
  })

  it('passes when a single type carries the whole quiz', () => {
    expect(generationCountsError(counts(0, 0, 0, 4), limits)).toBeNull()
  })

  it('blocks a zero total', () => {
    expect(generationCountsError(counts(0, 0, 0, 0), limits)).toMatch(/хотя бы один/)
  })

  it('blocks a total over the ceiling even when each type is within its own cap', () => {
    expect(generationCountsError(counts(10, 10, 10, 0), limits)).toMatch(/20/)
  })

  it('blocks a negative or fractional per-type count', () => {
    expect(generationCountsError(counts(-1, 0, 0, 0), limits)).not.toBeNull()
    expect(generationCountsError(counts(1.5, 0, 0, 0), limits)).not.toBeNull()
  })

  it('blocks while the limits have not loaded', () => {
    expect(generationCountsError(counts(3, 1, 1, 0), null)).not.toBeNull()
  })
})
