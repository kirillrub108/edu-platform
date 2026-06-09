// Static display metadata for the billing UI. Not a state singleton — just a
// module of constants/helpers (same pattern as useCreationMode.ts).

export interface OperationMeta {
  label: string
}

// Maps CreditOperation enum values → human labels (Russian).
export const OPERATION_LABELS: Record<string, string> = {
  GRANT: 'Начисление',
  TOPUP: 'Пополнение',
  LESSON_GENERATE: 'Генерация видео',
  LESSON_REGEN: 'Перегенерация видео',
  VISION_ANALYZE: 'Анализ презентации',
  SLIDE_REGEN: 'Регенерация слайда',
  RESERVE: 'Резервирование',
  RELEASE: 'Возврат резерва',
  EXPIRE: 'Сгорание кредитов',
}

// CREDIT_WEIGHTS keys → human labels for the "стоимость операций" table.
export const COST_LABELS: Record<string, string> = {
  lesson_generate: 'Генерация видео из презентации',
  lesson_regen: 'Повторная генерация видео',
  vision_analyze: 'Анализ презентации (vision)',
  slide_regen: 'Регенерация текста одного слайда',
  quiz_grade: 'AI-проверка теста',
}

export interface PlanMeta {
  label: string
  tagline: string
  accent: string // tailwind text/border accent for the plan card
}

export const PLAN_META: Record<string, PlanMeta> = {
  free: { label: 'Free', tagline: 'Для знакомства', accent: 'gray' },
  starter: { label: 'Starter', tagline: 'Для отдельных курсов', accent: 'violet' },
  pro: { label: 'Pro', tagline: 'Для активных преподавателей', accent: 'fuchsia' },
  school: { label: 'School', tagline: 'Для команд и учебных заведений', accent: 'indigo' },
}

export const PLAN_ORDER = ['free', 'starter', 'pro', 'school'] as const

export function operationLabel(op: string): string {
  return OPERATION_LABELS[op] ?? op
}

export function planLabel(plan: string): string {
  return PLAN_META[plan]?.label ?? plan
}

// Translate raw backend/task error strings into a friendly credits message.
export function friendlyTaskError(raw?: string | null): string | null {
  if (!raw) return null
  if (raw === 'insufficient_credits' || /недостаточно кредит/i.test(raw)) {
    return 'Недостаточно кредитов. Пополните баланс, чтобы продолжить.'
  }
  return raw
}

export function isInsufficientCredits(raw?: string | null): boolean {
  return !!raw && (raw === 'insufficient_credits' || /недостаточно кредит/i.test(raw))
}

// Translate a thrown apiFetch error into a friendly Russian message. Handles the
// structured tier-quota detail ({code, ...}) the backend returns on 402/429, the
// plain-string detail used elsewhere, and falls back to null when unclassifiable.
export function friendlyApiError(err: any): string | null {
  const detail = err?.data?.detail
  if (detail && typeof detail === 'object') {
    if (detail.code === 'quota_exceeded') {
      const what = detail.resource === 'vision' ? 'анализов презентаций' : 'генераций видео'
      return `Исчерпана месячная квота ${what} (использовано ${detail.used} из ${detail.limit}). `
        + 'Лимит обновится в начале следующего месяца.'
    }
    if (detail.code === 'concurrency_limit') {
      return `Слишком много одновременных задач (активно ${detail.active} из ${detail.limit}). `
        + 'Дождитесь завершения текущих и попробуйте снова.'
    }
  }
  if (typeof detail === 'string') return detail
  return null
}

export function formatRub(n: number): string {
  return new Intl.NumberFormat('ru-RU').format(n) + ' ₽'
}

export function formatDateTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString('ru-RU', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}
