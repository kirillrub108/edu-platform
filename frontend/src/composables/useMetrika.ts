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

// The four business goals configured in the Metrika counter (type "JavaScript-событие").
export const METRIKA_GOALS = {
  signup: 'signup',
  pptxUpload: 'pptx_upload',
  videoReady: 'video_ready',
  lessonPublish: 'lesson_publish',
} as const

export type MetrikaGoal = (typeof METRIKA_GOALS)[keyof typeof METRIKA_GOALS]

export function useMetrika() {
  // Empty NUXT_PUBLIC_METRIKA_ID (dev/test default) → counterId 0 → everything no-ops.
  const counterId = Number(useRuntimeConfig().public.metrikaId) || 0
  const auth = useAuthStore()

  // Track anonymous visitors (marketing funnel) and teachers; never students or
  // any other logged-in non-teacher role. Re-evaluated on every call so SPA
  // login/logout (no reload) flips tracking correctly.
  const shouldTrack = (): boolean =>
    counterId > 0 && (!auth.isAuthenticated || auth.user?.role === 'teacher')

  const reachGoal = (goal: MetrikaGoal, params?: Record<string, unknown>): void => {
    try {
      if (!import.meta.client) return
      if (!shouldTrack()) return
      if (typeof window.ym !== 'function') return
      window.ym(counterId, 'reachGoal', goal, params)
    } catch {
      /* analytics must never break the app */
    }
  }

  // Idempotent within the current tab: a goal already fired for this key
  // (e.g. a lesson id) is not sent again, surviving SSE/poll duplicates and F5.
  const reachGoalOnce = (goal: MetrikaGoal, key: string, params?: Record<string, unknown>): void => {
    const storageKey = `ym:${goal}:${key}`
    try {
      if (typeof sessionStorage !== 'undefined' && sessionStorage.getItem(storageKey)) return
    } catch {
      /* sessionStorage unavailable (private mode) — fall through and send once for this call */
    }
    reachGoal(goal, params)
    try {
      sessionStorage.setItem(storageKey, '1')
    } catch {
      /* ignore — worst case this goal can fire again later in the same tab */
    }
  }

  return { counterId, shouldTrack, reachGoal, reachGoalOnce }
}
