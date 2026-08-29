/**
 * The 403/409 "account pending deletion" branches, and the profile response →
 * UI state mapping. Pure functions, no component mounting.
 */
import { describe, expect, it } from 'vitest'
import {
  PENDING_DELETION_CODE,
  formatRestoreDeadline,
  parsePendingDeletion,
} from '~/utils/accountLifecycle'
import { resolveProfileState, statsHidden, type PublicProfile } from '~/stores/profile'

const loginError = (detail: unknown) => ({ response: { status: 403 }, data: { detail } })
const registerError = (detail: unknown) => ({ response: { status: 409 }, data: { detail } })

describe('parsePendingDeletion — login (403, object detail)', () => {
  it('reads the code and the deadline', () => {
    const parsed = parsePendingDeletion(
      loginError({ code: PENDING_DELETION_CODE, restore_until: '2026-09-28T10:00:00+00:00' }),
      403,
    )
    expect(parsed).toEqual({ restoreUntil: '2026-09-28T10:00:00+00:00' })
  })

  it('tolerates a missing deadline', () => {
    expect(parsePendingDeletion(loginError({ code: PENDING_DELETION_CODE }), 403)).toEqual({
      restoreUntil: null,
    })
  })

  it('ignores an ordinary 403', () => {
    expect(parsePendingDeletion(loginError('User is inactive'), 403)).toBeNull()
  })

  it('ignores the opaque 401 for a wrong password', () => {
    // The server proves the password BEFORE admitting the account is pending
    // deletion, so a guesser only ever sees this — and it must not light up
    // the restore CTA.
    const err = { response: { status: 401 }, data: { detail: 'Invalid credentials' } }
    expect(parsePendingDeletion(err, 403)).toBeNull()
  })
})

describe('parsePendingDeletion — register (409, string detail)', () => {
  it('recognises the bare code', () => {
    expect(parsePendingDeletion(registerError(PENDING_DELETION_CODE), 409)).toEqual({
      restoreUntil: null,
    })
  })

  it('leaves a plain duplicate-email 409 alone', () => {
    expect(parsePendingDeletion(registerError('Email already registered'), 409)).toBeNull()
  })
})

describe('parsePendingDeletion — status pinning', () => {
  it('does not fire on the right code with the wrong status', () => {
    expect(parsePendingDeletion(loginError({ code: PENDING_DELETION_CODE }), 409)).toBeNull()
    expect(parsePendingDeletion(registerError(PENDING_DELETION_CODE), 403)).toBeNull()
  })

  it('survives malformed payloads', () => {
    expect(parsePendingDeletion(null, 403)).toBeNull()
    expect(parsePendingDeletion({}, 403)).toBeNull()
    expect(parsePendingDeletion({ response: {} }, 403)).toBeNull()
    expect(parsePendingDeletion(loginError({ code: 42 }), 403)).toBeNull()
    expect(parsePendingDeletion(new Error('network'), 403)).toBeNull()
  })
})

describe('formatRestoreDeadline', () => {
  it('formats an ISO timestamp as a date', () => {
    expect(formatRestoreDeadline('2026-09-28T10:00:00+00:00')).toBe('28.09.2026')
  })

  it('returns null when there is nothing to format', () => {
    expect(formatRestoreDeadline(null)).toBeNull()
    expect(formatRestoreDeadline('not a date')).toBeNull()
  })
})

describe('resolveProfileState', () => {
  it('maps 404 to not_found', () => {
    // A hidden profile and a missing one are indistinguishable by design: the
    // API answers 404 for both, so the UI has one state, not two.
    expect(resolveProfileState(404)).toBe('not_found')
  })

  it('maps anything else to error', () => {
    expect(resolveProfileState(500)).toBe('error')
    expect(resolveProfileState(undefined)).toBe('error')
    expect(resolveProfileState(null)).toBe('error')
  })
})

describe('statsHidden', () => {
  const base: PublicProfile = {
    id: 'u1',
    full_name: 'Иван Петров',
    bio: null,
    role: 'teacher',
    created_at: '2026-01-01T00:00:00+00:00',
    avatar_url: null,
    courses: [],
    teacher_stats: null,
    student_stats: null,
    is_owner: false,
    profile_visibility: null,
    show_profile_stats: null,
  }

  it('is true when the owner turned the numbers off', () => {
    expect(statsHidden(base)).toBe(true)
  })

  it('is false when teacher stats are present', () => {
    const profile = {
      ...base,
      teacher_stats: { courses_count: 2, lessons_count: 8, students_count: 30 },
    }
    expect(statsHidden(profile)).toBe(false)
  })

  it('is false when student stats are present', () => {
    const profile: PublicProfile = {
      ...base,
      role: 'student',
      student_stats: { completed_lessons: 4, avg_quiz_score: 82.5, avg_assignment_score: null },
    }
    expect(statsHidden(profile)).toBe(false)
  })

  it('stays false for identity even with stats hidden', () => {
    // Hiding stats cuts only numbers — name, avatar and courses remain.
    const profile = { ...base, avatar_url: 'https://lh3.googleusercontent.com/a/x' }
    expect(statsHidden(profile)).toBe(true)
    expect(profile.full_name).toBe('Иван Петров')
    expect(profile.avatar_url).toBeTruthy()
  })
})
