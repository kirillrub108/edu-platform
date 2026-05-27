import { $fetch, type FetchOptions } from 'ofetch'

// Singleflight: if a burst of 401s fires at once, only ONE /auth/refresh call
// runs — the rest await the same promise so we don't burn multiple rotations.
let refreshPromise: Promise<boolean> | null = null

const isAuthEndpoint = (path: string): boolean =>
  path.startsWith('/auth/refresh') ||
  path.startsWith('/auth/login') ||
  path.startsWith('/auth/register')

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

      if (is401 && import.meta.client && !isAuthEndpoint(path)) {
        store.clearSession()
        await navigateTo('/login')
      }
      throw err
    }
  }

  return { apiFetch }
}
