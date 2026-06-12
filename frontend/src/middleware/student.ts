export default defineNuxtRouteMiddleware(() => {
  if (!import.meta.client) return

  const auth = useAuthStore()

  // Mirror of middleware/teacher.ts: bounce non-students out of the student
  // cabinet. Runs after the `auth` middleware has populated the session.
  if (auth.user && auth.user.role !== 'student') {
    return navigateTo('/dashboard')
  }
})
