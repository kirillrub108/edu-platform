/**
 * Client-side cooldown after a 429 from a rate-limited auth endpoint
 * (/auth/register, /auth/login). Prefers the server's Retry-After header;
 * main.py's rate_limit_exceeded_handler doesn't currently send one, so this
 * falls back to a fixed cooldown — see docs/DECISIONS.md §60.
 */

const FALLBACK_COOLDOWN_SECONDS = 30

interface FetchErrorLike {
  response?: { status?: number; headers?: Headers }
}

const parseRetryAfterSeconds = (err: unknown): number => {
  const raw = (err as FetchErrorLike)?.response?.headers?.get?.('Retry-After')
  const seconds = raw ? Number(raw) : NaN
  return Number.isFinite(seconds) && seconds > 0 ? seconds : FALLBACK_COOLDOWN_SECONDS
}

export const useRateLimitCooldown = () => {
  const remaining = ref(0)
  let timer: ReturnType<typeof setInterval> | null = null

  const start = (seconds: number) => {
    if (timer) clearInterval(timer)
    remaining.value = Math.ceil(seconds)
    timer = setInterval(() => {
      remaining.value -= 1
      if (remaining.value <= 0 && timer) {
        clearInterval(timer)
        timer = null
      }
    }, 1000)
  }

  const triggerFrom429 = (err: unknown) => start(parseRetryAfterSeconds(err))

  onScopeDispose(() => {
    if (timer) clearInterval(timer)
  })

  return { remaining, triggerFrom429 }
}
