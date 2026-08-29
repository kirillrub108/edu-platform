/**
 * Avatar source selection and the initials fallback.
 *
 * Pure functions only — this project has no @vue/test-utils (npm is banned,
 * see CLAUDE.md), so UserAvatar's logic lives in utils/avatar.ts precisely so
 * it can be asserted here without mounting anything.
 */
import { describe, expect, it } from 'vitest'
import {
  AVATAR_PALETTE,
  DELETED_USER_NAME,
  avatarColorClass,
  avatarInitials,
  displayName,
  profileLink,
} from '~/utils/avatar'

describe('avatarInitials', () => {
  it('takes the first letter of the first two words', () => {
    expect(avatarInitials({ full_name: 'Иван Петров' })).toBe('ИП')
    expect(avatarInitials({ full_name: 'Ada Lovelace' })).toBe('AL')
  })

  it('ignores words beyond the second', () => {
    expect(avatarInitials({ full_name: 'Иван Сергеевич Петров' })).toBe('ИС')
  })

  it('collapses extra whitespace', () => {
    expect(avatarInitials({ full_name: '  Иван   Петров  ' })).toBe('ИП')
  })

  it('handles a single-word name', () => {
    expect(avatarInitials({ full_name: 'Мадонна' })).toBe('М')
  })

  it('falls back to email when there is no name', () => {
    expect(avatarInitials({ full_name: null, email: 'kirill@example.com' })).toBe('K')
  })

  it('returns a placeholder rather than an empty string', () => {
    expect(avatarInitials(null)).toBe('?')
    expect(avatarInitials({ full_name: '   ' })).toBe('?')
    expect(avatarInitials({ full_name: null, email: null })).toBe('?')
  })
})

describe('displayName', () => {
  it('prefers the name, then the email', () => {
    expect(displayName({ full_name: 'Иван', email: 'i@e.com' })).toBe('Иван')
    expect(displayName({ full_name: null, email: 'i@e.com' })).toBe('i@e.com')
  })

  it('renders an anonymized/absent user as the deleted placeholder', () => {
    // Course.owner arrives as null once the teacher is soft-deleted or purged.
    expect(displayName(null)).toBe(DELETED_USER_NAME)
    expect(displayName({ full_name: null, email: null })).toBe(DELETED_USER_NAME)
  })
})

describe('avatarColorClass', () => {
  it('is deterministic for a given id', () => {
    const id = '8cd5d847-4d25-4e8c-96da-dc43ee38c7fc'
    expect(avatarColorClass(id)).toBe(avatarColorClass(id))
  })

  it('always returns a class from the palette', () => {
    for (let i = 0; i < 50; i++) {
      expect(AVATAR_PALETTE).toContain(avatarColorClass(`user-${i}`))
    }
  })

  it('spreads ids across more than one colour', () => {
    const seen = new Set(Array.from({ length: 50 }, (_, i) => avatarColorClass(`user-${i}`)))
    expect(seen.size).toBeGreaterThan(1)
  })

  it('has a neutral tint when there is no id', () => {
    expect(avatarColorClass(null)).toBe('bg-gray-100 text-gray-500')
    expect(avatarColorClass(undefined)).toBe('bg-gray-100 text-gray-500')
  })
})

describe('profileLink', () => {
  it('links to /u/{id} when there is an id', () => {
    expect(profileLink({ id: 'abc' })).toBe('/u/abc')
  })

  it('leads nowhere for a deleted user', () => {
    expect(profileLink(null)).toBeNull()
    expect(profileLink({ id: null })).toBeNull()
  })
})

describe('avatar source selection', () => {
  // Mirrors UserAvatar: render the image when there is a URL and it has not
  // failed to load, otherwise initials. The backend already collapses the
  // uploaded/provider pair into one avatar_url, so the client never chooses.
  const source = (avatarUrl: string | null, failed: boolean) =>
    failed || !avatarUrl ? 'initials' : 'image'

  it('uses the image when a url is present', () => {
    expect(source('https://lh3.googleusercontent.com/a/x', false)).toBe('image')
    expect(source('/files/avatars/1/a.webp?sig=x', false)).toBe('image')
  })

  it('falls back to initials with no url', () => {
    expect(source(null, false)).toBe('initials')
  })

  it('falls back to initials when the external image fails to load', () => {
    // A provider avatar is loaded cross-origin and can 403 or vanish.
    expect(source('https://lh3.googleusercontent.com/a/gone', true)).toBe('initials')
  })
})
