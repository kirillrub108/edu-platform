/**
 * Client-side mirrors of the auth form limits enforced server-side in
 * backend/app/schemas/auth.py — keep both in sync by hand when either changes.
 */

// Mirrors PasswordStr's min_length in schemas/auth.py.
export const PASSWORD_MIN_LENGTH = 8

// Mirrors UserRegister.full_name's max_length (== User.full_name column, String(255)).
export const FULL_NAME_MAX_LENGTH = 255

export const isValidEmail = (value: string): boolean =>
  /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim())

/**
 * Domain case never matters (DNS is case-insensitive) and the backend
 * silently lowercases it via Pydantic's EmailStr on save — normalize it here
 * too so what the user sees matches what gets stored. The local part (before
 * @) is left exactly as typed, since it can be case-sensitive.
 */
export const normalizeEmailDomain = (value: string): string => {
  const at = value.lastIndexOf('@')
  if (at === -1) return value
  return value.slice(0, at + 1) + value.slice(at + 1).toLowerCase()
}
