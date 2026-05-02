import { $fetch, type FetchOptions } from 'ofetch'

export const useApi = () => {
  const config = useRuntimeConfig()
  const base = config.public.apiBase as string

  const getToken = (): string | null =>
    import.meta.client ? localStorage.getItem('access_token') : null

  const apiFetch = async <T = unknown>(
    path: string,
    options: FetchOptions = {},
  ): Promise<T> => {
    const headers: Record<string, string> = {
      ...(options.headers as Record<string, string> | undefined),
    }
    const token = getToken()
    if (token) headers.Authorization = `Bearer ${token}`

    try {
      return (await $fetch<T>(path, {
        baseURL: base,
        ...options,
        headers,
      })) as T
    } catch (err: any) {
      if (err?.response?.status === 401 && import.meta.client) {
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
        await navigateTo('/login')
      }
      throw err
    }
  }

  return { apiFetch }
}
