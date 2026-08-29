/**
 * Avatar presentation logic, kept out of the component so it can be tested
 * directly — this project has no @vue/test-utils (npm is banned, see CLAUDE.md),
 * so anything worth asserting on has to be a plain function.
 *
 * Two initials algorithms used to exist side by side (AppHeader took the first
 * two characters, CommentItem took the first letter of the first two words).
 * This is the single one; UserAvatar is the only component that renders them.
 */

export const DELETED_USER_NAME = 'Удалённый пользователь'

export interface AvatarSubject {
  id?: string | null
  full_name?: string | null
  email?: string | null
  avatar_url?: string | null
}

export type AvatarSize = 'sm' | 'md' | 'lg'

export const AVATAR_SIZE_CLASSES: Record<AvatarSize, string> = {
  sm: 'w-8 h-8 text-xs',
  md: 'w-10 h-10 text-sm',
  lg: 'w-20 h-20 text-2xl',
}

/**
 * Fallback tints. Fixed Tailwind class strings, not interpolated — the JIT
 * compiler only sees classes that appear literally in the source.
 */
export const AVATAR_PALETTE: readonly string[] = [
  'bg-violet-100 text-violet-700',
  'bg-sky-100 text-sky-700',
  'bg-emerald-100 text-emerald-700',
  'bg-amber-100 text-amber-700',
  'bg-rose-100 text-rose-700',
  'bg-indigo-100 text-indigo-700',
  'bg-teal-100 text-teal-700',
]

/** A null subject is a user who was deleted and anonymized — not an error. */
export const displayName = (subject: AvatarSubject | null | undefined): string => {
  if (!subject) return DELETED_USER_NAME
  return subject.full_name || subject.email || DELETED_USER_NAME
}

/** Up to two letters: initials of the first two words, else the first letter. */
export const avatarInitials = (subject: AvatarSubject | null | undefined): string => {
  const source = subject?.full_name?.trim() || subject?.email?.trim() || ''
  if (!source) return '?'
  const words = source.split(/\s+/).filter(Boolean).slice(0, 2)
  const letters = words.map((w) => w[0]?.toUpperCase() ?? '').join('')
  return letters || '?'
}

/**
 * Deterministic palette pick, so one person keeps one colour everywhere and
 * across reloads. FNV-1a: tiny, well distributed, and no dependency.
 */
export const avatarColorClass = (userId: string | null | undefined): string => {
  if (!userId) return 'bg-gray-100 text-gray-500'
  let hash = 0x811c9dc5
  for (let i = 0; i < userId.length; i++) {
    hash ^= userId.charCodeAt(i)
    hash = Math.imul(hash, 0x01000193) >>> 0
  }
  return AVATAR_PALETTE[hash % AVATAR_PALETTE.length]!
}

/** Link target for a person, or null when there is no profile to link to. */
export const profileLink = (subject: AvatarSubject | null | undefined): string | null =>
  subject?.id ? `/u/${subject.id}` : null
