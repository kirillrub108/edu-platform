export default defineNuxtRouteMiddleware(async () => {
  if (!import.meta.client) return

  // csrf_token is non-httpOnly: its presence means the user has an active session
  const hasCsrf = document.cookie.includes('csrf_token=')
  if (!hasCsrf) return

  const auth = useAuthStore()

  if (!auth.user) {
    try {
      await auth.fetchMe()
    } catch {
      return
    }
  }

  if (!auth.user) return

  const role = auth.user.role
  return navigateTo(role === 'student' ? '/student/dashboard' : '/dashboard')
})
