import { defineStore } from 'pinia'

interface UserOut {
  id: string
  email: string
  full_name: string | null
  role: 'teacher' | 'student'
  is_active: boolean
  created_at: string
}

export const useAuthStore = defineStore('auth', () => {
  const { apiFetch } = useApi()
  const user = ref<UserOut | null>(null)
  const isAuthenticated = computed(() => !!user.value)

  const clearSession = () => {
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
    await apiFetch('/auth/login', {
      method: 'POST',
      body: { email, password, remember_me: rememberMe },
    })
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
    try {
      await apiFetch('/auth/logout', { method: 'POST' })
    } catch {
      /* noop — cookies are cleared server-side regardless */
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
  }
})
