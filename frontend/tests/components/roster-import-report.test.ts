/**
 * CourseRosterImport.vue report rendering + the client-side CSV export.
 *
 * @vue/test-utils isn't a dependency (npm is banned in this repo), so the SFC's
 * <template> is compiled with `vue/compiler-sfc` and mounted into happy-dom;
 * setup state is supplied by the harness, as in social-links.test.ts.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import * as Vue from 'vue'
import { compileTemplate, parse } from 'vue/compiler-sfc'
import {
  ROSTER_IMPORT_MAX_FILE_MB,
  ROSTER_IMPORT_MAX_ROWS,
  reportToCsv,
  rosterReasonLabel,
  type RosterImportReport,
} from '~/utils/rosterImport'

const source = readFileSync(
  resolve(process.cwd(), 'src/components/CourseRosterImport.vue'),
  'utf-8',
)
const { descriptor } = parse(source, { filename: 'CourseRosterImport.vue' })
const { code, errors } = compileTemplate({
  source: descriptor.template!.content,
  id: 'roster-import',
  filename: 'CourseRosterImport.vue',
  compilerOptions: { mode: 'function', prefixIdentifiers: false, cacheHandlers: false },
})
if (errors.length) throw errors[0]
const render = new Function('Vue', code)(Vue)

const REPORT: RosterImportReport = {
  needs_column_choice: false,
  columns: null,
  detected_column: { index: 2, header: 'Email' },
  total_rows: 3,
  added: 1,
  skipped: 2,
  results: [
    { row: 2, raw_value: 'ok@example.com', email: 'ok@example.com', status: 'added', reason: null },
    { row: 3, raw_value: 'Иванов И.И.', email: null, status: 'skipped', reason: 'invalid_email' },
    {
      row: 4,
      raw_value: 'old@example.com',
      email: 'old@example.com',
      status: 'skipped',
      reason: 'already_in_list',
    },
  ],
}

function mount(report: RosterImportReport) {
  const host = document.createElement('div')
  document.body.appendChild(host)
  const problems = report.results.filter((r) => r.status === 'skipped')
  const app = Vue.createApp({
    render,
    setup: () => ({
      open: true,
      file: null,
      dragging: false,
      uploading: false,
      error: '',
      report,
      chosenColumn: null,
      showAllRows: false,
      problems,
      shownRows: problems,
      Upload: 'span',
      X: 'span',
      ROSTER_IMPORT_MAX_ROWS,
      ROSTER_IMPORT_MAX_FILE_MB,
      rosterReasonLabel,
      pick: () => {},
      onPick: () => {},
      onDrop: () => {},
      upload: () => {},
      reset: () => {},
      downloadCsv: () => {},
    }),
  })
  app.config.warnHandler = () => {}
  app.mount(host)
  return host
}

describe('CourseRosterImport report', () => {
  it('summarises the import and lists only the skipped rows with RU reasons', () => {
    const text = mount(REPORT).textContent ?? ''
    expect(text).toContain('Добавлено 1 из 3')
    expect(text).toContain('колонка «Email»')
    expect(text).toContain('Пропущено строк: 2')
    expect(text).toContain('Не похоже на email')
    expect(text).toContain('Уже в списке')
    expect(text).not.toContain('ok@example.com')
  })

  it('states the file requirements from the shared limits', () => {
    const text = mount(REPORT).textContent ?? ''
    expect(text).toContain(`До ${ROSTER_IMPORT_MAX_ROWS} строк`)
    expect(text).toContain(`${ROSTER_IMPORT_MAX_FILE_MB} МБ`)
  })
})

describe('reportToCsv', () => {
  it('builds a BOM-prefixed semicolon CSV of every row', () => {
    const csv = reportToCsv(REPORT)
    expect(csv.startsWith('\uFEFF')).toBe(true)
    const lines = csv.replace('\uFEFF', '').trimEnd().split('\r\n')
    expect(lines).toHaveLength(4)
    expect(lines[0]).toBe('"Строка";"Значение";"Email";"Статус";"Причина"')
    expect(lines[1]).toBe('"2";"ok@example.com";"ok@example.com";"Добавлен";""')
    expect(lines[2]).toBe('"3";"Иванов И.И.";"";"Пропущен";"Не похоже на email"')
  })

  it('escapes embedded quotes', () => {
    const csv = reportToCsv({
      ...REPORT,
      results: [
        { row: 1, raw_value: 'a "b" c', email: null, status: 'skipped', reason: 'invalid_email' },
      ],
    })
    expect(csv).toContain('"a ""b"" c"')
  })
})
