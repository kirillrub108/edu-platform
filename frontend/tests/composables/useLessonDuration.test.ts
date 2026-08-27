/**
 * Detail levels and the duration they imply. These mirror backend
 * app/services/duration_service.py — the assertions below are what keeps the
 * two implementations from drifting.
 */

import { describe, expect, it } from 'vitest'
import {
  DETAIL_LEVEL_OPTIONS,
  DEFAULT_DETAIL_LEVEL,
  DetailLevel,
  WORDS_PER_MINUTE,
  countWords,
  estimateDurationSec,
  expectedDurationLabel,
  expectedDurationSec,
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
  it('is null when there are no slides yet', () => {
    expect(slideWordBudgets(DetailLevel.AUTO, 0)).toBeNull()
  })

  it('falls back to the default level for an unknown value', () => {
    expect(slideWordBudgets(null, 4)).toEqual(slideWordBudgets(DEFAULT_DETAIL_LEVEL, 4))
  })

  it('splits two slides evenly — no body slide to contrast with', () => {
    const budgets = slideWordBudgets(DetailLevel.AUTO, 2)!
    expect(budgets[0]).toBe(budgets[1])
  })

  it('gives title and closing slides less than body slides', () => {
    const budgets = slideWordBudgets(DetailLevel.AUTO, 5)!
    expect(budgets).toHaveLength(5)
    expect(budgets[0]).toBe(budgets[4])
    expect(budgets[0]).toBeLessThan(budgets[1])
    expect(budgets[1]).toBe(budgets[2])
    expect(budgets[2]).toBe(budgets[3])
  })

  it('gives every slide more words as the detail level rises', () => {
    const brief = slideWordBudgets(DetailLevel.BRIEF, 6)!
    const auto = slideWordBudgets(DetailLevel.AUTO, 6)!
    const high = slideWordBudgets(DetailLevel.HIGH, 6)!
    brief.forEach((b, i) => {
      expect(b).toBeLessThan(auto[i])
      expect(auto[i]).toBeLessThan(high[i])
    })
  })

  it('never drops below one word per slide', () => {
    expect(Math.min(...slideWordBudgets(DetailLevel.BRIEF, 3)!)).toBeGreaterThanOrEqual(1)
  })
})

describe('expectedDurationSec', () => {
  it('grows with the detail level', () => {
    expect(expectedDurationSec(DetailLevel.BRIEF, 10))
      .toBeLessThan(expectedDurationSec(DetailLevel.AUTO, 10))
    expect(expectedDurationSec(DetailLevel.AUTO, 10))
      .toBeLessThan(expectedDurationSec(DetailLevel.HIGH, 10))
  })

  it('grows with the deck', () => {
    expect(expectedDurationSec(DetailLevel.AUTO, 10))
      .toBeLessThan(expectedDurationSec(DetailLevel.AUTO, 20))
  })

  it('is zero without slides', () => {
    expect(expectedDurationSec(DetailLevel.AUTO, 0)).toBe(0)
  })

  it('matches the budgets it hands out', () => {
    const budgets = slideWordBudgets(DetailLevel.HIGH, 8)!
    const total = budgets.reduce((a, b) => a + b, 0)
    expect(expectedDurationSec(DetailLevel.HIGH, 8)).toBe(estimateDurationSec(total))
  })
})

describe('expectedDurationLabel', () => {
  it('is null until the deck is known', () => {
    expect(expectedDurationLabel(DetailLevel.AUTO, 0)).toBeNull()
  })

  it('rounds to whole minutes', () => {
    expect(expectedDurationLabel(DetailLevel.AUTO, 10)).toMatch(/^≈ \d+ мин$/)
  })

  it('never shows "0 мин" for a deck that does have slides', () => {
    expect(expectedDurationLabel(DetailLevel.BRIEF, 1)).toBe('≈ 1 мин')
  })
})

describe('DETAIL_LEVEL_OPTIONS', () => {
  it('offers exactly the three levels, shallowest first', () => {
    expect(DETAIL_LEVEL_OPTIONS.map(o => o.value)).toEqual(['brief', 'auto', 'high'])
  })

  it('defaults to the middle one', () => {
    expect(DEFAULT_DETAIL_LEVEL).toBe(DetailLevel.AUTO)
  })
})
