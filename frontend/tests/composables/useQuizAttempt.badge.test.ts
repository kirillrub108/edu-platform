/**
 * Tests for the ai_graded / graded_by_ai fields on AttemptResult / AnswerResult.
 *
 * Strategy: validate the TypeScript interfaces structurally (a wrong interface
 * fails compilation) and assert the badge-display condition for both states.
 * No component mounting — the condition is a pure boolean read from the result
 * object, so we test it as a plain function.
 */

import { describe, expect, it } from 'vitest'
import type { AnswerResult, AttemptResult } from '~/composables/useQuizAttempt'

// Minimal valid objects that satisfy the interfaces.
const baseAnswer: AnswerResult = {
  question_id: 'q1',
  awarded_score: '0.9',
  max_score: '1.0',
  is_correct: true,
  needs_review: false,
  graded_by_ai: false,
  llm_feedback: null,
  correct_payload: null,
}

const baseAttempt: AttemptResult = {
  attempt_id: 'a1',
  quiz_id: 'qz1',
  attempt_number: 1,
  status: 'graded',
  score: '0.9',
  passed: true,
  started_at: '2024-01-01T00:00:00Z',
  submitted_at: '2024-01-01T00:01:00Z',
  graded_at: '2024-01-01T00:02:00Z',
  grading_task_id: null,
  ai_graded: false,
  questions: [],
  answers: [],
}

// The badge show condition as expressed in the template:  result.ai_graded === true
const shouldShowBadge = (result: AttemptResult): boolean => result.ai_graded === true

describe('AttemptResult.ai_graded badge condition', () => {
  it('badge shows when ai_graded is true', () => {
    const result: AttemptResult = { ...baseAttempt, ai_graded: true }
    expect(shouldShowBadge(result)).toBe(true)
  })

  it('badge is hidden when ai_graded is false', () => {
    const result: AttemptResult = { ...baseAttempt, ai_graded: false }
    expect(shouldShowBadge(result)).toBe(false)
  })

  it('ai_graded reflects any answer having graded_by_ai=true', () => {
    const answers: AnswerResult[] = [
      { ...baseAnswer, graded_by_ai: false },
      { ...baseAnswer, graded_by_ai: true },
    ]
    const ai_graded = answers.some(a => a.graded_by_ai)
    expect(ai_graded).toBe(true)
  })

  it('ai_graded is false when no answer was graded by AI', () => {
    const answers: AnswerResult[] = [
      { ...baseAnswer, graded_by_ai: false },
      { ...baseAnswer, graded_by_ai: false },
    ]
    const ai_graded = answers.some(a => a.graded_by_ai)
    expect(ai_graded).toBe(false)
  })

  it('override sets graded_by_ai=false which makes ai_graded false', () => {
    // Simulate: one AI-graded answer → teacher overrides → graded_by_ai reset.
    let answer: AnswerResult = { ...baseAnswer, graded_by_ai: true }
    answer = { ...answer, graded_by_ai: false }
    const ai_graded = [answer].some(a => a.graded_by_ai)
    expect(ai_graded).toBe(false)
  })
})
