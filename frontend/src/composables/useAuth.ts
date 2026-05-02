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

  const fetchMe = async () => {
    if (!import.meta.client) return  // не выполнять на сервере
    try {
      user.value = await apiFetch<UserOut>('/auth/me')
    } catch {
      user.value = null
    }
  }

  const login = async (email: string, password: string) => {
    const tokens = await apiFetch<TokenResponse>('/auth/login', {
      method: 'POST',
      body: { email, password },
    })
    persistTokens(tokens)
    await fetchMe()
  }

  const register = async (email: string, password: string, full_name?: string) => {
    const tokens = await apiFetch<TokenResponse>('/auth/register', {
      method: 'POST',
      body: { email, password, full_name },
    })
    persistTokens(tokens)
    await fetchMe()
  }

  const logout = async () => {
    if (import.meta.client) {
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
    }
    user.value = null
    await navigateTo('/login')
  }

  const isAuthenticated = computed(() => !!user.value)

  return { user, isAuthenticated, login, register, logout, fetchMe }
}
