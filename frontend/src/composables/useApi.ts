import { $fetch, type FetchOptions } from 'ofetch'

// Singleflight: if a burst of 401s fires at once, only ONE /auth/refresh call
// runs — the rest await the same promise so we don't burn multiple rotations.
let refreshPromise: Promise<boolean> | null = null

// ── Error parsing ─────────────────────────────────────────────────────────────

interface Pydantic422Item {
  type: string
  loc: string[]
  msg: string
  ctx?: Record<string, unknown>
}

export interface ParsedApiError {
  /** field name → first human-readable RU error (from Pydantic 422) */
  fields: Record<string, string>
  /** general error message (non-field 422 items, or any non-422 error) */
  general: string
}

function mapPydanticMessage(item: Pydantic422Item): string {
  const { type, msg, ctx } = item
  if (type === 'missing') return 'Обязательное поле'
  if (type === 'string_too_short') {
    const min = ctx?.min_length
    return typeof min === 'number' ? `Минимум ${min} символов` : 'Слишком короткое значение'
  }
  if (type === 'value_error' && (msg.includes('@') || msg.toLowerCase().includes('email'))) {
    return 'Некорректный email'
  }
  return msg
}

const KNOWN_DETAIL_RU: Record<string, string> = {
  'Email already registered': 'Email уже зарегистрирован',
}

function mapGeneralError(err: unknown): string {
  const status = (err as { response?: { status?: number } })?.response?.status
  if (!status) return 'Сервис недоступен, попробуйте позже'
  if (status === 429) return 'Слишком много попыток, попробуйте позже'
  if (status >= 500) return 'Сервис недоступен, попробуйте позже'
  const detail = (err as { data?: { detail?: unknown } })?.data?.detail
  if (typeof detail === 'string') return KNOWN_DETAIL_RU[detail] ?? detail
  return 'Ошибка запроса'
}

/**
 * Normalize any $fetch error into a structured, human-readable form.
 * 422 responses produce per-field messages; everything else goes into `general`.
 * Existing callers that access err.data directly are unaffected — this is additive.
 */
export function parseApiError(err: unknown): ParsedApiError {
  const status = (err as { response?: { status?: number } })?.response?.status
  const detail = (err as { data?: { detail?: unknown } })?.data?.detail

  if (status === 422 && Array.isArray(detail)) {
    const fields: Record<string, string> = {}
    const generalMsgs: string[] = []

    for (const item of detail as Pydantic422Item[]) {
      // loc is typically ["body", "fieldName"]; take the last segment as field key
      const last = item.loc?.at(-1)
      const fieldKey = typeof last === 'string' && last !== 'body' ? last : null
      const message = mapPydanticMessage(item)

      if (fieldKey) {
        if (!fields[fieldKey]) fields[fieldKey] = message
      } else {
        generalMsgs.push(message)
      }
    }

    return { fields, general: generalMsgs.join('; ') }
  }

  return { fields: {}, general: mapGeneralError(err) }
}

const isAuthEndpoint = (path: string): boolean =>
  path.startsWith('/auth/refresh') ||
  path.startsWith('/auth/login') ||
  path.startsWith('/auth/register')

// /auth/me is a session probe: a 401 just means "anonymous", not "session died".
// Public pages (landing/login/register) probe it via AppHeader, so it must never
// trigger the auto-logout redirect — only genuine in-session calls should.
const isSessionProbe = (path: string): boolean => path.startsWith('/auth/me')

const getCsrfToken = (): string | null => {
  if (!import.meta.client) return null
  // csrf_token is non-httpOnly so JS can read it for the double-submit pattern.
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/)
  return match ? decodeURIComponent(match[1]) : null
}

export const useApi = () => {
  const config = useRuntimeConfig()
  const base = config.public.apiBase as string

  const tryRefresh = async (): Promise<boolean> => {
    if (!import.meta.client) return false

    if (!refreshPromise) {
      // No body — refresh_token is in an httpOnly cookie.
      // Explicit empty headers: must not forward a stale X-CSRF-Token here.
      refreshPromise = $fetch('/auth/refresh', {
        baseURL: base,
        method: 'POST',
        credentials: 'include',
        headers: {},
      })
        .then(() => true)
        .catch(() => false)
        .finally(() => {
          refreshPromise = null
        })
    }
    return refreshPromise
  }

  const apiFetch = async <T = unknown>(
    path: string,
    options: FetchOptions<'json'> = {},
    _isRetry = false,
  ): Promise<T> => {
    const store = useAuthStore()

    const headers: Record<string, string> = {
      ...(options.headers as Record<string, string> | undefined),
    }

    // Double-submit CSRF: read the non-httpOnly csrf_token cookie and forward
    // it as X-CSRF-Token for all state-changing requests (except auth flows
    // that set the cookie in the first place).
    const method = (options.method as string | undefined)?.toUpperCase() ?? 'GET'
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method) && !isAuthEndpoint(path)) {
      const csrf = getCsrfToken()
      if (csrf) headers['X-CSRF-Token'] = csrf
    }

    try {
      return (await $fetch<T>(path, {
        baseURL: base,
        credentials: 'include',
        ...options,
        headers,
      })) as T
    } catch (err: any) {
      const is401 = err?.response?.status === 401

      // Reactive refresh: covers the case where the server clock is ahead and
      // the access token expired between requests. Skip on auth endpoints
      // (refreshing a failed /auth/login is moot; /auth/refresh looping is
      // dangerous) and on retry (the fresh token was also rejected — dead session).
      if (is401 && !_isRetry && import.meta.client && !isAuthEndpoint(path)) {
        const ok = await tryRefresh()
        if (ok) {
          // New cookies are set by the server. Re-read csrf_token for the retry.
          const newCsrf = getCsrfToken()
          if (newCsrf && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
            headers['X-CSRF-Token'] = newCsrf
          }
          return apiFetch<T>(path, options, true)
        }
      }

      if (is401 && import.meta.client && !isAuthEndpoint(path) && !isSessionProbe(path)) {
        store.clearSession()
        await navigateTo('/login')
      }
      throw err
    }
  }

  return { apiFetch }
}
