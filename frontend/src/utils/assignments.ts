// Pure helpers for the assignments UI — kept side-effect-free so component
// logic (submit-enabled, file validation, points validation) is unit-testable.

export function fileExt(name: string): string {
  const i = name.lastIndexOf('.')
  return i >= 0 ? name.slice(i + 1).toLowerCase() : ''
}

export function isExtAllowed(name: string, allowed: string[]): boolean {
  return allowed.includes(fileExt(name))
}

export function isFileTooLarge(sizeBytes: number, maxMb: number): boolean {
  return sizeBytes > maxMb * 1024 * 1024
}

/** A submission is sendable once it has non-empty text OR at least one file. */
export function submissionIsComplete(
  text: string | null | undefined,
  fileCount: number,
): boolean {
  return (text?.trim().length ?? 0) > 0 || fileCount > 0
}

/** Returns an error message for an out-of-range points value, or null if valid. */
export function validatePoints(value: number | null, maxPoints: number): string | null {
  if (value === null || Number.isNaN(value)) return 'Введите балл'
  if (value < 0) return 'Балл не может быть отрицательным'
  if (value > maxPoints) return `Максимум ${maxPoints}`
  return null
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function formatAssignmentDateTime(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
