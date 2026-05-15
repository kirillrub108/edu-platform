export default defineNuxtRouteMiddleware(async () => {
  if (!import.meta.client) return

  const token = localStorage.getItem('access_token')
  if (!token) return

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
