// Yandex.Metrika integration — shared gate + goals.
//
// Single source of truth for "is this visitor tracked?" so the client plugin
// (which sends per-navigation hits) and any component sending conversion goals
// agree without duplicating the rule. Loading/hit logic lives in
// plugins/metrika.client.ts; this composable owns the gate and reachGoal.

type YmFunction = (counterId: number, action: string, ...params: unknown[]) => void

declare global {
  interface Window {
    ym?: YmFunction
  }
}

export function useMetrika() {
  // Empty NUXT_PUBLIC_METRIKA_ID (dev/test default) → counterId 0 → everything no-ops.
  const counterId = Number(useRuntimeConfig().public.metrikaId) || 0
  const auth = useAuthStore()

  // Track anonymous visitors (marketing funnel) and teachers; never students or
  // any other logged-in non-teacher role. Re-evaluated on every call so SPA
  // login/logout (no reload) flips tracking correctly.
  const shouldTrack = (): boolean =>
    counterId > 0 && (!auth.isAuthenticated || auth.user?.role === 'teacher')

  const goal = (name: string, params?: Record<string, unknown>): void => {
    if (!shouldTrack()) return
    if (typeof window === 'undefined' || typeof window.ym !== 'function') return
    window.ym(counterId, 'reachGoal', name, params)
  }

  return { counterId, shouldTrack, goal }
}
