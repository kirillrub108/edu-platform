import { $fetch, type FetchOptions } from 'ofetch'

interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

// Singleflight: if a burst of requests gets 401 simultaneously, only ONE
// /auth/refresh call runs — the rest await the same promise. Without this
// every parallel request would burn a refresh-token rotation, and only the
// last one would land in localStorage; the others would race and 401 again.
let refreshPromise: Promise<TokenResponse | null> | null = null

const isAuthEndpoint = (path: string): boolean =>
  path.startsWith('/auth/refresh') ||
  path.startsWith('/auth/login') ||
  path.startsWith('/auth/register')

export const useApi = () => {
  const config = useRuntimeConfig()
  const base = config.public.apiBase as string

  const getToken = (): string | null =>
    import.meta.client ? localStorage.getItem('access_token') : null

  const tryRefresh = async (): Promise<TokenResponse | null> => {
    if (!import.meta.client) return null
    const refresh_token = localStorage.getItem('refresh_token')
    if (!refresh_token) return null

    if (!refreshPromise) {
      refreshPromise = $fetch<TokenResponse>('/auth/refresh', {
        baseURL: base,
        method: 'POST',
        body: { refresh_token },
      })
        .then((tokens) => {
          localStorage.setItem('access_token', tokens.access_token)
          localStorage.setItem('refresh_token', tokens.refresh_token)
          return tokens
        })
        .catch(() => null)
        .finally(() => {
          // Clear after resolution so a *future* 401 burst can refresh again.
          refreshPromise = null
        })
    }
    return refreshPromise
  }

  const apiFetch = async <T = unknown>(
    path: string,
    options: FetchOptions = {},
    _retried = false,
  ): Promise<T> => {
    const headers: Record<string, string> = {
      ...(options.headers as Record<string, string> | undefined),
    }
    const token = getToken()
    if (token) headers.Authorization = `Bearer ${token}`

    try {
      return (await $fetch<T>(path, {
        baseURL: base,
        ...options,
        headers,
      })) as T
    } catch (err: any) {
      const is401 = err?.response?.status === 401

      // Try to silently rotate tokens and replay the request once. Skip for
      // the auth endpoints themselves — refreshing on a failed /auth/refresh
      // would loop, and refreshing on a wrong-password /auth/login is moot.
      if (is401 && !_retried && import.meta.client && !isAuthEndpoint(path)) {
        const tokens = await tryRefresh()
        if (tokens) {
          return apiFetch<T>(path, options, true)
        }
      }

      // Refresh impossible or also failed → user is genuinely logged out.
      if (is401 && import.meta.client && !isAuthEndpoint(path)) {
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
        await navigateTo('/login')
      }
      throw err
    }
  }

  return { apiFetch }
}
