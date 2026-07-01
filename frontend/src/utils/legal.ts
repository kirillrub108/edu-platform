// Single source of truth for the sole proprietor's legal requisites, contacts
// and legal-document metadata. Auto-imported by Nuxt (utils/*). Every legal
// page, the landing footer and the billing consent block read from here — do
// NOT inline requisites anywhere else.
import { SUPPORT_EMAIL } from './support'

export const LEGAL_ENTITY = {
  fullName: 'Индивидуальный предприниматель Рубец Кирилл Сергеевич',
  shortName: 'ИП Рубец К. С.',
  inn: '290219787381',
  ogrnip: '326290000028753',
  registeredAt: '22.06.2026',
  registrar:
    'Управление ФНС по Архангельской области и Ненецкому автономному округу',
  taxRegime: 'АУСН',
  // Wording to reproduce verbatim in documents where VAT status is required.
  vatNote: 'НДС не облагается (применяется АУСН)',
  primaryOkved: {
    code: '62.01',
    title: 'Разработка компьютерного программного обеспечения',
  },
  additionalOkved: [
    '85.41',
    '85.42',
    '62.02',
    '62.09',
    '63.11',
    '63.11.1',
    '63.12',
    '58.29',
    '59.12',
    '47.91.2',
  ],
} as const

export const LEGAL_BANK = {
  bankName: 'ФИЛИАЛ "ЦЕНТРАЛЬНЫЙ" БАНКА ВТБ (ПАО)',
  account: '40802810590810003454',
  corrAccount: '30101810145250000411',
  bik: '044525411',
} as const

export const LEGAL_CONTACTS = {
  site: 'https://edllm.ru',
  siteLabel: 'edllm.ru',
  // Support e-mail is the primary channel for all legal requests (consent
  // withdrawal, refunds, subject-rights requests). Reused from support.ts so
  // the address is defined once.
  supportEmail: SUPPORT_EMAIL,
  phone: '+7 911 672-77-75',
  phoneHref: '+79116727775',
} as const

export const REFUND_TERMS = {
  // Channel and turnaround for unused-credit refund requests.
  requestChannel: SUPPORT_EMAIL,
  processingWorkingDays: 10,
} as const

export type LegalDocKey =
  | 'offer'
  | 'privacy'
  | 'pdn-consent'
  | 'refund'
  | 'contacts'

export interface LegalDocumentMeta {
  key: LegalDocKey
  title: string
  // Compact label for footer / inline links.
  shortTitle: string
  route: string
  version: string
  updatedAt: string
}

// Bump these two together whenever any legal document text changes.
// LEGAL_DOCS_VERSION is the policy revision key and MUST match the backend's
// CONSENT_POLICY_VERSION (app/constants.py), so recorded consents reference the
// exact revision shown to the user.
export const LEGAL_DOCS_VERSION = '2026-07-01'
export const LEGAL_DOCS_UPDATED_AT = '01.07.2026'

export const LEGAL_DOCUMENTS: LegalDocumentMeta[] = [
  {
    key: 'offer',
    title: 'Публичная оферта',
    shortTitle: 'Публичная оферта',
    route: '/legal/offer',
    version: LEGAL_DOCS_VERSION,
    updatedAt: LEGAL_DOCS_UPDATED_AT,
  },
  {
    key: 'privacy',
    title: 'Политика конфиденциальности',
    shortTitle: 'Политика конфиденциальности',
    route: '/legal/privacy',
    version: LEGAL_DOCS_VERSION,
    updatedAt: LEGAL_DOCS_UPDATED_AT,
  },
  {
    key: 'pdn-consent',
    title: 'Согласие на обработку персональных данных',
    shortTitle: 'Согласие на обработку ПДн',
    route: '/legal/pdn-consent',
    version: LEGAL_DOCS_VERSION,
    updatedAt: LEGAL_DOCS_UPDATED_AT,
  },
  {
    key: 'refund',
    title: 'Политика возврата',
    shortTitle: 'Политика возврата',
    route: '/legal/refund',
    version: LEGAL_DOCS_VERSION,
    updatedAt: LEGAL_DOCS_UPDATED_AT,
  },
  {
    key: 'contacts',
    title: 'Контакты и реквизиты',
    shortTitle: 'Контакты и реквизиты',
    route: '/legal/contacts',
    version: LEGAL_DOCS_VERSION,
    updatedAt: LEGAL_DOCS_UPDATED_AT,
  },
]

export const legalDoc = (key: LegalDocKey): LegalDocumentMeta => {
  const doc = LEGAL_DOCUMENTS.find((d) => d.key === key)
  if (!doc) throw new Error(`Unknown legal document: ${key}`)
  return doc
}
