/**
 * Reading the two "this account is pending deletion" answers off an API error.
 *
 * The server speaks the same code from two places with two shapes:
 *   POST /auth/login    → 403, detail = { code, restore_until }
 *   POST /auth/register → 409, detail = "account_pending_deletion"
 *
 * Pure so it can be tested without mounting anything.
 */

export const PENDING_DELETION_CODE = 'account_pending_deletion'

interface ApiErrorLike {
  response?: { status?: number }
  data?: { detail?: unknown }
}

export interface PendingDeletion {
  /** ISO timestamp of the restore deadline, when the server sent one. */
  restoreUntil: string | null
}

const detailCode = (detail: unknown): string | null => {
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object' && 'code' in detail) {
    const code = (detail as { code?: unknown }).code
    return typeof code === 'string' ? code : null
  }
  return null
}

const detailRestoreUntil = (detail: unknown): string | null => {
  if (detail && typeof detail === 'object' && 'restore_until' in detail) {
    const value = (detail as { restore_until?: unknown }).restore_until
    return typeof value === 'string' ? value : null
  }
  return null
}

/**
 * The pending-deletion payload, or null when the error is something else.
 * `expectStatus` pins it to the status the calling endpoint actually uses, so a
 * matching code on an unrelated response cannot trigger the recovery UI.
 */
export const parsePendingDeletion = (
  err: unknown,
  expectStatus: number,
): PendingDeletion | null => {
  const e = err as ApiErrorLike
  if (e?.response?.status !== expectStatus) return null
  if (detailCode(e?.data?.detail) !== PENDING_DELETION_CODE) return null
  return { restoreUntil: detailRestoreUntil(e?.data?.detail) }
}

/** Human-readable deadline, or null when the server did not send one. */
export const formatRestoreDeadline = (iso: string | null): string | null => {
  if (!iso) return null
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return null
  return date.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' })
}
