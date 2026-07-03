/**
 * Client-side dry-run quiz grading used by the teacher «view as student»
 * preview (utils/quizGrading.ts): per-type auto-check semantics, open types
 * returning null, and stripping teacher payloads to the student shape.
 */
import { describe, expect, it } from 'vitest'

import {
  gradeAutoResponse,
  isAutoGradable,
  toStudentPayload,
} from '../../src/utils/quizGrading'

describe('isAutoGradable', () => {
  it('marks open (LLM-graded) types as not auto-gradable', () => {
    expect(isAutoGradable('short_answer')).toBe(false)
    expect(isAutoGradable('essay')).toBe(false)
    expect(isAutoGradable('single_choice')).toBe(true)
    expect(isAutoGradable('fill_blank')).toBe(true)
  })
})

describe('gradeAutoResponse', () => {
  it('single_choice: exact index match', () => {
    const payload = { prompt: 'q', options: ['a', 'b'], correct_index: 1 }
    expect(gradeAutoResponse('single_choice', payload, { selected_index: 1 })).toBe(true)
    expect(gradeAutoResponse('single_choice', payload, { selected_index: 0 })).toBe(false)
    expect(gradeAutoResponse('single_choice', payload, undefined)).toBe(false)
  })

  it('multiple_choice: set equality, order-insensitive', () => {
    const payload = { prompt: 'q', options: ['a', 'b', 'c'], correct_indices: [0, 2] }
    expect(gradeAutoResponse('multiple_choice', payload, { selected_indices: [2, 0] })).toBe(true)
    expect(gradeAutoResponse('multiple_choice', payload, { selected_indices: [0] })).toBe(false)
    expect(gradeAutoResponse('multiple_choice', payload, { selected_indices: [0, 1, 2] })).toBe(false)
  })

  it('true_false: boolean match', () => {
    const payload = { prompt: 'q', correct: false }
    expect(gradeAutoResponse('true_false', payload, { selected: false })).toBe(true)
    expect(gradeAutoResponse('true_false', payload, { selected: true })).toBe(false)
  })

  it('matching: pair-set equality, order-insensitive', () => {
    const payload = { prompt: 'q', left: ['l1', 'l2'], right: ['r1', 'r2'], correct_pairs: [[0, 1], [1, 0]] }
    expect(gradeAutoResponse('matching', payload, { pairs: [[1, 0], [0, 1]] })).toBe(true)
    expect(gradeAutoResponse('matching', payload, { pairs: [[0, 0], [1, 1]] })).toBe(false)
    expect(gradeAutoResponse('matching', payload, { pairs: [[0, 1]] })).toBe(false)
  })

  it('ordering: exact sequence match', () => {
    const payload = { prompt: 'q', items: ['a', 'b', 'c'], correct_order: [2, 0, 1] }
    expect(gradeAutoResponse('ordering', payload, { order: [2, 0, 1] })).toBe(true)
    expect(gradeAutoResponse('ordering', payload, { order: [0, 1, 2] })).toBe(false)
  })

  it('fill_blank: each blank matches any accepted variant, case-insensitive by default', () => {
    const payload = { prompt: '___ and ___', blanks: [['Foo'], ['Bar', 'Baz']] }
    expect(gradeAutoResponse('fill_blank', payload, { answers: ['foo', ' baz '] })).toBe(true)
    expect(gradeAutoResponse('fill_blank', payload, { answers: ['foo', 'nope'] })).toBe(false)
    expect(gradeAutoResponse('fill_blank', payload, { answers: ['foo'] })).toBe(false)
  })

  it('fill_blank: case-sensitive when case_insensitive=false', () => {
    const payload = { prompt: '___', blanks: [['Foo']], case_insensitive: false }
    expect(gradeAutoResponse('fill_blank', payload, { answers: ['foo'] })).toBe(false)
    expect(gradeAutoResponse('fill_blank', payload, { answers: ['Foo'] })).toBe(true)
  })

  it('open types return null (эталон/критерии shown instead of grading)', () => {
    expect(gradeAutoResponse('short_answer', { prompt: 'q', reference_answer: 'x' }, { text: 'x' })).toBeNull()
    expect(gradeAutoResponse('essay', { prompt: 'q', rubric: 'r' }, { text: 'anything' })).toBeNull()
  })
})

describe('toStudentPayload (answers stripped)', () => {
  it('never leaks correct answers into the student shape', () => {
    const stripped = toStudentPayload('single_choice', {
      prompt: 'q', options: ['a', 'b'], correct_index: 1, explanation: 'e',
    })
    expect(stripped).toEqual({ type: 'single_choice', prompt: 'q', options: ['a', 'b'] })
  })

  it('fill_blank exposes only the blank count', () => {
    const stripped = toStudentPayload('fill_blank', {
      prompt: '___ ___', blanks: [['a'], ['b']], case_insensitive: true,
    })
    expect(stripped).toEqual({ type: 'fill_blank', prompt: '___ ___', blanks_count: 2 })
  })

  it('essay keeps only the prompt (rubric stays teacher-side)', () => {
    expect(toStudentPayload('essay', { prompt: 'q', rubric: 'r' })).toEqual({
      type: 'essay', prompt: 'q',
    })
  })
})
