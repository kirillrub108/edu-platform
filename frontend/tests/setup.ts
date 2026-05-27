// Vitest setup: provide stubs for Nuxt auto-imports that useApi.ts relies on.
// The actual mock IMPLEMENTATIONS are installed per-test (see useApi.test.ts).
// This file only ensures the globals exist so module top-level evaluation does
// not crash when useApi.ts is imported.

import { vi } from 'vitest'

vi.stubGlobal('useRuntimeConfig', () => ({ public: { apiBase: 'http://api.test' } }))
vi.stubGlobal('useAuthStore', () => ({
  getAccessToken: () => null,
  getRefreshToken: () => null,
  persistTokens: () => undefined,
  clearSession: () => undefined,
}))
vi.stubGlobal('navigateTo', vi.fn(async () => undefined))
