/**
 * Teacher-facing surfaces for the AI-grading quota and attachment retention.
 *
 * No component-mount harness exists here (@vue/test-utils isn't a dependency
 * and npm is banned), so these assert the source of the components. Behavioural
 * coverage of the extend call lives in tests/stores/assignments.test.ts.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const read = (rel: string) => readFileSync(resolve(process.cwd(), rel), 'utf-8')

const widget = read('src/components/CreditBalanceWidget.vue')
const panel = read('src/components/assignments/TeacherPanel.vue')
const billingPage = read('src/pages/billing.vue')

describe('CreditBalanceWidget — AI quota next to the balance', () => {
  it('renders remaining/limit from the store getter', () => {
    expect(widget).toContain('aiGrading')
    expect(widget).toMatch(/aiGrading\.remaining\s*\}\}\s*из\s*\{\{\s*aiGrading\.limit/)
  })

  it('hides the quota row when the balance has no quota payload', () => {
    expect(widget).toContain('v-if="aiGrading"')
  })
})

describe('billing page — AI quota block', () => {
  it('shows the remaining allowance and when it resets', () => {
    expect(billingPage).toContain('AI-проверка ответов')
    expect(billingPage).toContain('aiQuotaResetLabel')
  })

  it('explains the degradation path when the quota is exhausted', () => {
    expect(billingPage).toContain('aiQuotaExhausted')
    expect(billingPage).toContain('ручную проверку')
  })
})

describe('TeacherPanel — retention column', () => {
  it('shows the expiry date and an extend button priced in credits', () => {
    expect(panel).toContain('Файлы до')
    expect(panel).toContain('expiryLabel(s.attachments_expire_at)')
    expect(panel).toMatch(/Продлить · \$\{s\.retention_extension_credits\} кр\./)
  })

  it('offers no extend control for a submission without attachments', () => {
    // Both the column body and canExtend() gate on attachment_count.
    expect(panel).toContain("s.attachment_count > 0 && s.attachments_expire_at")
    expect(panel).toMatch(/canExtend\s*=\s*\(s: SubmissionSummary\)\s*=>\s*\n?\s*s\.attachment_count > 0/)
  })

  it('branches 409 (files gone) and 402 (no credits) separately, not a catch-all', () => {
    expect(panel).toContain("status === 409 && err?.data?.detail?.code === 'attachments_already_removed'")
    expect(panel).toContain('status === 402')
    expect(panel).toContain('Не хватает кредитов')
    expect(panel).toContain('Файлы уже удалены')
  })

  it('updates the row in place after a successful extension, without reloading', () => {
    expect(panel).toContain('s.attachments_expire_at = updated.attachments_expire_at')
    expect(panel).toContain('s.retention_extension_credits = updated.retention_extension_credits')
    // The charge moved the balance, so the sidebar widget is refreshed too.
    expect(panel).toContain('billing.refresh()')
    expect(panel).not.toContain('window.location.reload')
  })

  it('disables the button while its own row is in flight', () => {
    expect(panel).toContain(':disabled="extendingId === s.id"')
    expect(panel).toContain('Продлеваем…')
  })
})
