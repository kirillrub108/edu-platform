/**
 * Pure assignment UI logic: submit-enabled gate, file validation, points
 * validation. These functions back the component behaviour (Submit.vue /
 * Review.vue) and are tested in isolation.
 */
import { describe, expect, it } from 'vitest'

import {
  fileExt,
  formatBytes,
  isExtAllowed,
  isFileTooLarge,
  submissionIsComplete,
  validatePoints,
} from '../../src/utils/assignments'

describe('submissionIsComplete (submit-enabled gate)', () => {
  it('false when no text and no files', () => {
    expect(submissionIsComplete('', 0)).toBe(false)
    expect(submissionIsComplete('   ', 0)).toBe(false)
    expect(submissionIsComplete(null, 0)).toBe(false)
    expect(submissionIsComplete(undefined, 0)).toBe(false)
  })
  it('true with non-empty text', () => {
    expect(submissionIsComplete('answer', 0)).toBe(true)
  })
  it('true with at least one file even if text empty', () => {
    expect(submissionIsComplete('', 1)).toBe(true)
    expect(submissionIsComplete('   ', 2)).toBe(true)
  })
})

describe('validatePoints', () => {
  it('rejects null / NaN', () => {
    expect(validatePoints(null, 100)).toBe('Введите балл')
    expect(validatePoints(Number.NaN, 100)).toBe('Введите балл')
  })
  it('rejects negative and above-max', () => {
    expect(validatePoints(-1, 100)).toBe('Балл не может быть отрицательным')
    expect(validatePoints(120, 100)).toBe('Максимум 100')
  })
  it('accepts in-range values incl. boundaries', () => {
    expect(validatePoints(0, 100)).toBeNull()
    expect(validatePoints(50, 100)).toBeNull()
    expect(validatePoints(100, 100)).toBeNull()
  })
})

describe('file validation', () => {
  it('fileExt extracts lower-case extension', () => {
    expect(fileExt('Essay.PDF')).toBe('pdf')
    expect(fileExt('archive.tar.gz')).toBe('gz')
    expect(fileExt('noext')).toBe('')
  })
  it('isExtAllowed checks against the allow-list', () => {
    expect(isExtAllowed('a.pdf', ['pdf', 'docx'])).toBe(true)
    expect(isExtAllowed('a.exe', ['pdf', 'docx'])).toBe(false)
  })
  it('isFileTooLarge compares bytes to the MB cap', () => {
    expect(isFileTooLarge(5 * 1024 * 1024, 10)).toBe(false)
    expect(isFileTooLarge(11 * 1024 * 1024, 10)).toBe(true)
    expect(isFileTooLarge(10 * 1024 * 1024, 10)).toBe(false)
  })
})

describe('formatBytes', () => {
  it('formats by magnitude', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(2048)).toBe('2 KB')
    expect(formatBytes(3 * 1024 * 1024)).toBe('3.0 MB')
  })
})
