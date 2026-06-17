import { defineStore } from 'pinia'

interface UserOut {
  id: string
  email: string
  full_name: string | null
  role: 'teacher' | 'student'
  is_active: boolean
  email_verified: boolean
  created_at: string
}

export const useAuthStore = defineStore('auth', () => {
  const { apiFetch } = useApi()
  const user = ref<UserOut | null>(null)
  const isAuthenticated = computed(() => !!user.value)
  const isEmailVerified = computed(() => !!user.value?.email_verified)

  // Global "verify your email" prompt. Opened by useAiGuard when an unverified
  // user clicks an AI action, or by the AppHeader badge. The modal itself is
  // mounted once in app.vue.
  const verifyPromptOpen = ref(false)
  const openVerifyPrompt = () => { verifyPromptOpen.value = true }
  const closeVerifyPrompt = () => { verifyPromptOpen.value = false }

  const clearSession = () => {
    user.value = null
    verifyPromptOpen.value = false
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

  // Anonymous: request a reset link. The server answers identically whether or
  // not the email exists, so there is nothing to branch on here.
  const forgotPassword = async (email: string) => {
    await apiFetch('/auth/forgot-password', { method: 'POST', body: { email } })
  }

  // Anonymous: consume the reset token and set a new password. Throws on an
  // invalid/expired/used token so the page can surface a single generic error.
  const resetPassword = async (token: string, newPassword: string) => {
    await apiFetch('/auth/reset-password', {
      method: 'POST',
      body: { token, new_password: newPassword },
    })
  }

  // Authenticated: the server rotates this session's cookies on success, so no
  // re-login or fetchMe is needed (the user object is unchanged).
  const changePassword = async (oldPassword: string, newPassword: string) => {
    await apiFetch('/auth/change-password', {
      method: 'POST',
      body: { old_password: oldPassword, new_password: newPassword },
    })
  }

  return {
    user,
    isAuthenticated,
    isEmailVerified,
    verifyPromptOpen,
    openVerifyPrompt,
    closeVerifyPrompt,
    login,
    register,
    logout,
    fetchMe,
    clearSession,
    forgotPassword,
    resetPassword,
    changePassword,
  }
})
