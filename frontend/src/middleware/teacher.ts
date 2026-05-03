export default defineNuxtRouteMiddleware(() => {
  if (!import.meta.client) return

  const { user } = useAuth()

  if (user.value && user.value.role !== 'teacher') {
    return navigateTo('/student/dashboard')
  }
})
