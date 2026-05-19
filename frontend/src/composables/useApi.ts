import { $fetch, type FetchOptions } from 'ofetch'

interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

// Singleflight: if a burst of requests gets 401 simultaneously, only ONE
// /auth/refresh call runs — the rest await the same promise. Without this
// every parallel request would burn a refresh-token rotation, and only the
// last one would land in the store; the others would race and 401 again.
let refreshPromise: Promise<TokenResponse | null> | null = null

const isAuthEndpoint = (path: string): boolean =>
  path.startsWith('/auth/refresh') ||
  path.startsWith('/auth/login') ||
  path.startsWith('/auth/register')

// Decode JWT exp without verifying the signature — we only need to know
// whether the token is *about* to be rejected by the server. The 5-second
// skew margin makes us refresh slightly BEFORE the server's clock would
// reject the token, so a request never goes out with an expired bearer.
const isAccessTokenExpired = (token: string): boolean => {
  // Browser-only — tokens never exist on the server side of this app
  // (routeRules sets ssr:false), so we can rely on `atob` here.
  if (!import.meta.client) return false
  try {
    const payload = token.split('.')[1]
    if (!payload) return true
    const b64 = payload.replace(/-/g, '+').replace(/_/g, '/')
    const padded = b64 + '='.repeat((4 - (b64.length % 4)) % 4)
    const decoded = JSON.parse(atob(padded))
    if (typeof decoded.exp !== 'number') return false
    return decoded.exp * 1000 < Date.now() + 5000
  } catch {
    // Malformed token → treat as expired so we attempt a refresh.
    return true
  }
}

export const useApi = () => {
  const config = useRuntimeConfig()
  const base = config.public.apiBase as string

  const tryRefresh = async (): Promise<TokenResponse | null> => {
    if (!import.meta.client) return null
    const store = useAuthStore()
    const refresh_token = store.getRefreshToken()
    if (!refresh_token) return null

    if (!refreshPromise) {
      refreshPromise = $fetch<TokenResponse>('/auth/refresh', {
        baseURL: base,
        method: 'POST',
        body: { refresh_token },
        // Explicit empty headers: must NOT forward a stale access token in
        // Authorization — that would cause the refresh request itself to 401.
        headers: {},
      })
        .then((tokens) => {
          store.persistTokens(tokens)
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
    _isRetry = false,
  ): Promise<T> => {
    const store = useAuthStore()

    // Proactive refresh: if the cached access token is already past its `exp`,
    // skip the doomed request and rotate first. Without this, every page load
    // after a 15-min idle would surface a noisy GET /auth/me 401 in the
    // browser console (recovered via retry, but visible) — and worse, parallel
    // requests racing on an expired token could each fail before the retry
    // kicks in, leaving UI buttons stuck in their `disabled/loading` state.
    let token = store.getAccessToken()
    if (
      token &&
      !_isRetry &&
      !isAuthEndpoint(path) &&
      import.meta.client &&
      isAccessTokenExpired(token)
    ) {
      const tokens = await tryRefresh()
      if (!tokens) {
        // Refresh failed — the session is dead. Don't fire the doomed request
        // anonymously; clear the stale tokens and bounce to /login so the user
        // gets a clear signal instead of a half-broken UI with stuck buttons.
        store.clearSession()
        await navigateTo('/login')
        throw new Error('Session expired')
      }
      token = tokens.access_token
    }

    const headers: Record<string, string> = {
      ...(options.headers as Record<string, string> | undefined),
    }
    if (token) headers.Authorization = `Bearer ${token}`

    try {
      return (await $fetch<T>(path, {
        baseURL: base,
        ...options,
        headers,
      })) as T
    } catch (err: any) {
      const is401 = err?.response?.status === 401

      // Reactive fallback: covers the rare case where the server clock is
      // ahead of ours and the proactive check let an "already-expired" token
      // through anyway. Skip on auth endpoints — refreshing a failed
      // /auth/refresh would loop, and refreshing on a wrong-password
      // /auth/login is moot. Skip on retry — if the fresh token is also
      // rejected, the session is genuinely dead; don't loop.
      if (is401 && !_isRetry && token && import.meta.client && !isAuthEndpoint(path)) {
        const tokens = await tryRefresh()
        if (tokens) {
          // All parallel callers that reached this point awaited the same
          // refreshPromise. Now each retries its own original request with
          // the new token from the store.
          return apiFetch<T>(path, options, true)
        }
      }

      // Refresh impossible or also failed → session expired (had a token) → redirect.
      // If there was no token at all, the user is simply unauthenticated — not an error.
      if (is401 && import.meta.client && !isAuthEndpoint(path)) {
        store.clearSession()
        if (token) await navigateTo('/login')
      }
      throw err
    }
  }

  return { apiFetch }
}
