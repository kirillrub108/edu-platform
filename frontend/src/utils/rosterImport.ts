/** Bulk roster import (course access tab): response types + report rendering. */

export type RosterImportReason =
  | 'invalid_email'
  | 'duplicate_in_file'
  | 'already_in_list'
  | 'is_course_owner'
  | 'not_registered'

export interface RosterColumnRef {
  index: number
  header: string
}

export interface RosterColumnOption extends RosterColumnRef {
  samples: string[]
}

export interface RosterImportRow {
  row: number
  raw_value: string
  email: string | null
  status: 'added' | 'skipped'
  reason: RosterImportReason | null
}

export interface RosterImportReport {
  needs_column_choice: boolean
  columns: RosterColumnOption[] | null
  detected_column: RosterColumnRef | null
  total_rows: number
  added: number
  skipped: number
  results: RosterImportRow[]
}

/** Server sends machine codes; the wording lives here. */
export const ROSTER_REASON_LABELS: Record<RosterImportReason, string> = {
  invalid_email: 'Не похоже на email',
  duplicate_in_file: 'Повтор в файле',
  already_in_list: 'Уже в списке',
  is_course_owner: 'Это ваш собственный адрес',
  not_registered: 'Не зарегистрирован на платформе',
}

export function rosterReasonLabel(reason: RosterImportReason | null): string {
  return reason ? (ROSTER_REASON_LABELS[reason] ?? reason) : ''
}

/** Limits mirrored from backend constants (ROSTER_IMPORT_*) for the hint and
 *  the client-side size pre-check. */
export const ROSTER_IMPORT_MAX_ROWS = 1000
export const ROSTER_IMPORT_MAX_FILE_MB = 2

function csvCell(value: string): string {
  return `"${value.replace(/"/g, '""')}"`
}

/** `;` + BOM so Excel opens it with the columns split and Cyrillic intact. */
export function reportToCsv(report: RosterImportReport): string {
  const head = ['Строка', 'Значение', 'Email', 'Статус', 'Причина']
  const rows = report.results.map((r) =>
    [
      String(r.row),
      r.raw_value,
      r.email ?? '',
      r.status === 'added' ? 'Добавлен' : 'Пропущен',
      rosterReasonLabel(r.reason),
    ].map(csvCell).join(';'),
  )
  return `\uFEFF${[head.map(csvCell).join(';'), ...rows].join('\r\n')}\r\n`
}
