/**
 * Duration arithmetic shared by the lesson form and the slide editor. These
 * mirror backend app/services/duration_service.py — the assertions below are
 * what keeps the two implementations from drifting.
 */

import { describe, expect, it } from 'vitest'
import {
  LESSON_DURATION_MAX_MINUTES,
  LESSON_DURATION_MIN_MINUTES,
  LESSON_DURATION_PRESETS_MIN,
  WORDS_PER_MINUTE,
  clampTargetDuration,
  countWords,
  estimateDurationSec,
  formatDuration,
  slideWordBudgets,
} from '~/composables/useLessonDuration'

describe('countWords', () => {
  it('ignores surrounding and repeated whitespace', () => {
    expect(countWords('  one   two\n\nthree \t four ')).toBe(4)
  })

  it('is zero for blank text', () => {
    expect(countWords('   ')).toBe(0)
  })
})

describe('estimateDurationSec', () => {
  it('turns a minute of words into 60 seconds', () => {
    expect(estimateDurationSec(WORDS_PER_MINUTE)).toBe(60)
  })

  it('is zero for no words', () => {
    expect(estimateDurationSec(0)).toBe(0)
  })
})

describe('formatDuration', () => {
  it('pads seconds', () => {
    expect(formatDuration(65)).toBe('1:05')
    expect(formatDuration(0)).toBe('0:00')
  })
})

describe('slideWordBudgets', () => {
  it('is null without a target (auto mode)', () => {
    expect(slideWordBudgets(null, 12)).toBeNull()
  })

  it('gives a single slide the whole budget', () => {
    expect(slideWordBudgets(10, 1)).toEqual([10 * WORDS_PER_MINUTE])
  })

  it('splits two slides evenly — no body slide to contrast with', () => {
    const budgets = slideWordBudgets(10, 2)!
    expect(budgets[0]).toBe(budgets[1])
  })

  it('gives title and closing slides less than body slides', () => {
    const budgets = slideWordBudgets(15, 5)!
    expect(budgets).toHaveLength(5)
    expect(budgets[0]).toBe(budgets[4])
    expect(budgets[0]).toBeLessThan(budgets[1])
    expect(budgets[1]).toBe(budgets[2])
    expect(budgets[2]).toBe(budgets[3])
  })

  it('adds up to the target, give or take per-slide rounding', () => {
    const budgets = slideWordBudgets(20, 7)!
    const total = budgets.reduce((a, b) => a + b, 0)
    expect(Math.abs(total - 20 * WORDS_PER_MINUTE)).toBeLessThanOrEqual(budgets.length)
  })

  it('never drops below one word per slide', () => {
    expect(Math.min(...slideWordBudgets(5, 5000)!)).toBe(1)
  })

  it('is null when there are no slides yet', () => {
    expect(slideWordBudgets(15, 0)).toBeNull()
  })
})

describe('clampTargetDuration', () => {
  it('passes null through as auto', () => {
    expect(clampTargetDuration(null)).toBeNull()
    expect(clampTargetDuration(Number.NaN)).toBeNull()
  })

  it('accepts any whole minute inside the range', () => {
    expect(clampTargetDuration(7)).toBe(7)
    expect(clampTargetDuration(42)).toBe(42)
  })

  it('rounds fractional input', () => {
    expect(clampTargetDuration(12.4)).toBe(12)
  })

  it('clamps to the bounds the backend accepts', () => {
    expect(clampTargetDuration(0)).toBe(LESSON_DURATION_MIN_MINUTES)
    expect(clampTargetDuration(9999)).toBe(LESSON_DURATION_MAX_MINUTES)
  })
})

describe('LESSON_DURATION_PRESETS_MIN', () => {
  it('offers the usual lesson lengths as quick picks', () => {
    expect([...LESSON_DURATION_PRESETS_MIN]).toEqual([5, 10, 15, 20, 30])
  })
})
