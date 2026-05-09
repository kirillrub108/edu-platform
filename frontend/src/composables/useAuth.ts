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

export const useAuth = () => {
  const { apiFetch } = useApi()
  const user = useState<UserOut | null>('auth.user', () => null)

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
    // Backend /register only creates the user (returns UserOut). Log in
    // immediately so the caller ends up authenticated like before.
    await apiFetch<UserOut>('/auth/register', {
      method: 'POST',
      body: { email, password, role, full_name },
    })
    await login(email, password, true)
  }

  const logout = async () => {
    if (import.meta.client) {
      const refresh_token = localStorage.getItem('refresh_token')
      // Best-effort revoke on the backend (blacklists access jti and
      // deletes the refresh family). Ignore errors — local state is
      // wiped regardless so the user always ends up logged out.
      try {
        await apiFetch('/auth/logout', {
          method: 'POST',
          body: { refresh_token },
        })
      } catch {
        /* noop */
      }
    }
    clearTokens()
    user.value = null
    await navigateTo('/login')
  }

  const isAuthenticated = computed(() => !!user.value)

  return { user, isAuthenticated, login, register, logout, fetchMe }
}
