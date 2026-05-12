export default defineNuxtRouteMiddleware(async () => {
  if (!import.meta.client) return

  const auth = useAuthStore()

  if (!auth.user) {
    await auth.fetchMe()
  }

  if (!auth.user) {
    return navigateTo('/login')
  }
})
