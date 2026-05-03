export default defineNuxtRouteMiddleware(async () => {
  if (!import.meta.client) return

  const { user, fetchMe } = useAuth()

  if (!user.value) {
    await fetchMe()
  }

  if (!user.value) {
    return navigateTo('/login')
  }
})
