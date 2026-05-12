export default defineNuxtRouteMiddleware(() => {
  if (!import.meta.client) return

  const auth = useAuthStore()

  if (auth.user && auth.user.role !== 'teacher') {
    return navigateTo('/student/dashboard')
  }
})
