/**
 * Route-guard semantics: public pages stay reachable for anonymous visitors,
 * private pages bounce them to /login.
 *
 * The app uses opt-in per-page middleware (not a global guard):
 *   - public pages (index/login/register/join) either declare no auth
 *     middleware or use `guest`, which only redirects ALREADY-logged-in users;
 *   - private pages opt in via definePageMeta({ middleware: ['auth', ...] }).
 *
 * These tests pin that behaviour at the middleware level so a future refactor
 * can't silently make the landing/login/register inaccessible to anonymous
 * users, or stop protecting private routes.
 *
 * Both middleware early-return on `!import.meta.client`; vitest.config.ts
 * rewrites `import.meta.client` → `true` for src/middleware so the client path
 * runs here. `defineNuxtRouteMiddleware` is stubbed as identity, and
 * useAuthStore/navigateTo are re-stubbed per test.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

type Role = 'teacher' | 'student'
interface FakeUser { role: Role }

let currentUser: FakeUser | null = null
let fetchMeYields: FakeUser | null = null
const navigateToMock = vi.fn(async () => undefined)

const installGlobals = (): void => {
  vi.stubGlobal('defineNuxtRouteMiddleware', (fn: unknown) => fn)
  vi.stubGlobal('navigateTo', navigateToMock)
  vi.stubGlobal('useAuthStore', () => ({
    get user() {
      return currentUser
    },
    fetchMe: vi.fn(async () => {
      currentUser = fetchMeYields
    }),
  }))
}

const setCookie = (value: string): void => {
  Object.defineProperty(document, 'cookie', { value, writable: true, configurable: true })
}

const loadGuest = async () => (await import('../../src/middleware/guest')).default as () => Promise<unknown>
const loadAuth = async () => (await import('../../src/middleware/auth')).default as () => Promise<unknown>

beforeEach(() => {
  vi.resetModules()
  navigateToMock.mockClear()
  currentUser = null
  fetchMeYields = null
  setCookie('')
  installGlobals()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('guest middleware (public landing)', () => {
  it('does NOT redirect an anonymous visitor (no csrf cookie)', async () => {
    setCookie('') // anonymous: no session cookie

    const guest = await loadGuest()
    await guest()

    expect(navigateToMock).not.toHaveBeenCalled()
  })

  it('redirects an already-logged-in teacher away from the landing', async () => {
    setCookie('csrf_token=abc')
    fetchMeYields = { role: 'teacher' }

    const guest = await loadGuest()
    await guest()

    expect(navigateToMock).toHaveBeenCalledWith('/dashboard')
  })

  it('redirects an already-logged-in student to their dashboard', async () => {
    setCookie('csrf_token=abc')
    fetchMeYields = { role: 'student' }

    const guest = await loadGuest()
    await guest()

    expect(navigateToMock).toHaveBeenCalledWith('/student/dashboard')
  })
})

describe('auth middleware (private routes)', () => {
  it('redirects an anonymous visitor to /login', async () => {
    currentUser = null
    fetchMeYields = null // fetchMe resolves but leaves user null

    const auth = await loadAuth()
    await auth()

    expect(navigateToMock).toHaveBeenCalledWith('/login')
  })

  it('lets an authenticated user through (no redirect)', async () => {
    currentUser = { role: 'teacher' }

    const auth = await loadAuth()
    await auth()

    expect(navigateToMock).not.toHaveBeenCalled()
  })
})
