import { defineStore } from 'pinia'

interface UserOut {
  id: string
  email: string
  full_name: string | null
  role: 'teacher' | 'student'
  is_active: boolean
  created_at: string
}

interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

export const useAuthStore = defineStore('auth', () => {
  const { apiFetch } = useApi()
  const user = ref<UserOut | null>(null)
  const isAuthenticated = computed(() => !!user.value)

  const getAccessToken = (): string | null =>
    import.meta.client ? localStorage.getItem('access_token') : null

  const getRefreshToken = (): string | null =>
    import.meta.client ? localStorage.getItem('refresh_token') : null

  const persistTokens = (tokens: TokenResponse) => {
    if (!import.meta.client) return
    localStorage.setItem('access_token', tokens.access_token)
    localStorage.setItem('refresh_token', tokens.refresh_token)
  }

  const clearTokens = () => {
    if (!import.meta.client) return
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
  }

  const clearSession = () => {
    clearTokens()
    user.value = null
  }

  const fetchMe = async () => {
    if (!import.meta.client) return
    try {
      user.value = await apiFetch<UserOut>('/auth/me')
    } catch {
      user.value = null
    }
  }

  const login = async (email: string, password: string, rememberMe: boolean = true) => {
    const tokens = await apiFetch<TokenResponse>('/auth/login', {
      method: 'POST',
      body: { email, password, remember_me: rememberMe },
    })
    persistTokens(tokens)
    await fetchMe()
  }

  const register = async (
    email: string,
    password: string,
    role: 'teacher' | 'student',
    full_name?: string,
  ) => {
    await apiFetch<UserOut>('/auth/register', {
      method: 'POST',
      body: { email, password, role, full_name },
    })
    await login(email, password, true)
  }

  const logout = async () => {
    if (import.meta.client) {
      const refresh_token = getRefreshToken()
      try {
        await apiFetch('/auth/logout', {
          method: 'POST',
          body: { refresh_token },
        })
      } catch {
        /* noop */
      }
    }
    clearSession()
    await navigateTo('/login')
  }

  return {
    user,
    isAuthenticated,
    login,
    register,
    logout,
    fetchMe,
    clearSession,
    getAccessToken,
    getRefreshToken,
    persistTokens,
  }
})
