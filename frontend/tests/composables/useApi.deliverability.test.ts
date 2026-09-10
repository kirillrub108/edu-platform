/**
 * Registration must tell "this domain cannot receive mail" apart from "we don't
 * take throwaway inboxes" — the two need different actions from the user, and
 * both used to collapse into the generic "Некорректный email".
 */

import { describe, expect, it } from 'vitest'
import { parseApiError } from '~/composables/useApi'

const err = (status: number, detail: unknown) => ({
  response: { status },
  data: { detail },
})

describe('parseApiError — deliverability', () => {
  it('maps the dead-domain 422 to its own message', () => {
    const parsed = parseApiError(err(422, 'undeliverable_email_domain'))
    expect(parsed.general).toContain('почтовых серверов')
  })

  it('maps a suppressed address to a different message', () => {
    const parsed = parseApiError(err(422, 'email_suppressed'))
    expect(parsed.general).toContain('не доставляются')
    expect(parsed.general).not.toContain('почтовых серверов')
  })

  it('keeps the disposable-domain error distinct from a syntax error', () => {
    const parsed = parseApiError(
      err(422, [
        {
          loc: ['body', 'email'],
          type: 'value_error',
          msg: 'Value error, disposable_email_not_allowed',
        },
      ]),
    )
    expect(parsed.fields.email).toBe('Одноразовые почтовые адреса не поддерживаются')
  })

  it('still reports a genuinely malformed address as a syntax error', () => {
    const parsed = parseApiError(
      err(422, [
        {
          loc: ['body', 'email'],
          type: 'value_error',
          msg: 'value is not a valid email address',
        },
      ]),
    )
    expect(parsed.fields.email).toBe('Некорректный email')
  })

  it('translates the change-email conflicts', () => {
    expect(parseApiError(err(409, 'email_unchanged')).general).toBe('Это ваш текущий адрес.')
    expect(parseApiError(err(409, 'Email already registered')).general).toBe(
      'Email уже зарегистрирован',
    )
  })
})
