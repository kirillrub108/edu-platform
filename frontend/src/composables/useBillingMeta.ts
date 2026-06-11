// Static display metadata for the billing UI. Not a state singleton — just a
// module of constants/helpers (same pattern as useCreationMode.ts).

export interface OperationMeta {
  label: string
}

// Maps CreditOperation enum values → human labels (Russian).
export const OPERATION_LABELS: Record<string, string> = {
  GRANT: 'Начисление',
  TOPUP: 'Пополнение',
  PURCHASE: 'Покупка кредитов',
  LESSON_GENERATE: 'Генерация видео',
  LESSON_REGEN: 'Перегенерация видео',
  VISION_ANALYZE: 'Анализ презентации',
  SLIDE_REGEN: 'Регенерация слайда',
  QUIZ_GENERATE: 'Генерация теста',
  AI_REVIEW: 'AI-проверка вопросов',
  RESERVE: 'Резервирование',
  RELEASE: 'Возврат резерва',
  EXPIRE: 'Сгорание кредитов',
}

// CREDIT_WEIGHTS keys → human labels for the "стоимость операций" table.
export const COST_LABELS: Record<string, string> = {
  vision_analyze: 'Анализ презентации (vision)',
  slide_regen: 'Регенерация текста одного слайда',
  quiz_generate: 'Генерация теста',
  ai_review: 'AI-review вопросов',
  quiz_grade: 'AI-проверка теста',
}

export function operationLabel(op: string): string {
  return OPERATION_LABELS[op] ?? op
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

// Parse a fetch error whose `data.detail` may be a machine-readable object
// ({code, ...}) or a plain string. `insufficient` signals the caller should
// show a "пополнить баланс" CTA.
export function friendlyApiError(err: any): { message: string; insufficient: boolean } {
  const detail = err?.data?.detail
  if (detail && typeof detail === 'object') {
    if (detail.code === 'insufficient_credits') {
      return {
        message: `Недостаточно кредитов: нужно ${detail.required} CR, доступно ${detail.available} CR.`,
        insufficient: true,
      }
    }
    if (detail.code === 'trial_exhausted') {
      return {
        message: `Бесплатный лимит исчерпан (${detail.used} из ${detail.limit}). Купите кредиты, чтобы продолжить.`,
        insufficient: true,
      }
    }
    if (detail.code === 'generation_in_progress') {
      return { message: 'Генерация уже запущена.', insufficient: false }
    }
  }
  if (typeof detail === 'string') {
    return {
      message: friendlyTaskError(detail) ?? detail,
      insufficient: isInsufficientCredits(detail),
    }
  }
  return { message: 'Что-то пошло не так', insufficient: false }
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
