import { defineStore } from 'pinia'

export interface UserOut {
  id: string
  email: string
  full_name: string | null
  role: 'teacher' | 'student'
  is_active: boolean
  email_verified: boolean
  created_at: string
  /** Single computed field: uploaded avatar wins, else the provider's. */
  avatar_url: string | null
}

export type OAuthProvider = 'google' | 'yandex'
export type ProfileVisibility = 'public' | 'authenticated' | 'private'

export interface ProfileSettings {
  full_name: string | null
  bio: string | null
  avatar_url: string | null
}

export interface PrivacySettings {
  profile_visibility: ProfileVisibility
  show_profile_stats: boolean
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
    full_name: string | undefined,
    consents: {
      accepted_privacy: boolean
      accepted_terms: boolean
      accepted_marketing: boolean
    },
  ) => {
    await apiFetch<UserOut>('/auth/register', {
      method: 'POST',
      body: { email, password, role, full_name, ...consents },
    })
    await login(email, password, true)
  }

  // Social sign-in. The server parks state + PKCE verifier and hands back the
  // provider's authorize URL; we leave the SPA with a full page load (no popup,
  // no fetch to the provider) and come back on the cookie-setting callback.
  const oauthStart = async (provider: OAuthProvider, next?: string) => {
    const { authorize_url } = await apiFetch<{ authorize_url: string }>(
      `/auth/oauth/${provider}/start`,
      { method: 'POST', body: { remember_me: true, next: next ?? null } },
    )
    window.location.href = authorize_url
  }

  // Finish a social registration: the ticket is one-shot, so a second submit
  // (another tab) fails instead of creating a duplicate account.
  const oauthComplete = async (
    ticket: string,
    role: 'teacher' | 'student',
    consents: { pdn_consent: boolean; offer_consent: boolean; marketing_consent: boolean },
  ): Promise<string> => {
    const { redirect } = await apiFetch<{ redirect: string }>('/auth/oauth/complete', {
      method: 'POST',
      body: { ticket, role, ...consents },
    })
    await fetchMe()
    return redirect
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

  // ── Own profile / privacy / account ────────────────────────────────────────
  // These mutate the signed-in identity, so the header avatar and name have to
  // follow: every writer mirrors the fresh values onto `user`.

  const fetchProfileSettings = () => apiFetch<ProfileSettings>('/users/me/profile')

  const applyProfile = (settings: ProfileSettings) => {
    if (user.value) {
      user.value.full_name = settings.full_name
      user.value.avatar_url = settings.avatar_url
    }
    return settings
  }

  const updateProfile = async (patch: Partial<Pick<ProfileSettings, 'full_name' | 'bio'>>) =>
    applyProfile(await apiFetch<ProfileSettings>('/users/me/profile', {
      method: 'PATCH',
      body: patch,
    }))

  const uploadAvatar = async (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return applyProfile(await apiFetch<ProfileSettings>('/users/me/avatar', {
      method: 'POST',
      body: form,
    }))
  }

  // Removes the uploaded file only. A provider-supplied picture, if any, comes
  // back — that is what "revert to my Google avatar" means.
  const deleteAvatar = async () =>
    applyProfile(await apiFetch<ProfileSettings>('/users/me/avatar', { method: 'DELETE' }))

  const fetchPrivacy = () => apiFetch<PrivacySettings>('/users/me/privacy')

  const updatePrivacy = (patch: Partial<PrivacySettings>) =>
    apiFetch<PrivacySettings>('/users/me/privacy', { method: 'PATCH', body: patch })

  // Soft delete. The server clears the cookies, so the local session goes too.
  const deleteAccount = async (password: string) => {
    await apiFetch('/users/me/delete', { method: 'POST', body: { password } })
    clearSession()
  }

  // Anonymous: undo a soft delete by token or by credentials, then sign in.
  const restoreAccount = async (payload: {
    token?: string
    email?: string
    password?: string
  }) => {
    await apiFetch('/auth/restore-account', { method: 'POST', body: payload })
    await fetchMe()
  }

  // Anonymous, always 204 — never branch on the outcome.
  const requestEmailRelease = async (email: string) => {
    await apiFetch('/auth/release-email', { method: 'POST', body: { email } })
  }

  const confirmEmailRelease = async (token: string) => {
    await apiFetch('/auth/confirm-release', { method: 'POST', body: { token } })
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
    oauthStart,
    oauthComplete,
    fetchProfileSettings,
    updateProfile,
    uploadAvatar,
    deleteAvatar,
    fetchPrivacy,
    updatePrivacy,
    deleteAccount,
    restoreAccount,
    requestEmailRelease,
    confirmEmailRelease,
  }
})
