import { defineConfig } from 'vitest/config'
import { fileURLToPath } from 'node:url'
import type { Plugin } from 'vite'

// Nuxt provides `import.meta.client` via build-time replacement. Vite's
// `define` option does NOT cover `import.meta.*` properties (only literal
// identifiers), so we replace it at transform time for any module under
// src/composables. useApi.ts gates browser-only paths behind this flag and
// we need those paths exercised in tests.
const importMetaClientPlugin: Plugin = {
  name: 'replace-import-meta-client',
  enforce: 'pre',
  transform(code, id) {
    if (!id.includes('src/composables/') && !id.includes('src\\composables\\')) return null
    if (!code.includes('import.meta.client')) return null
    return code.replace(/import\.meta\.client/g, 'true')
  },
}

export default defineConfig({
  plugins: [importMetaClientPlugin],
  test: {
    environment: 'happy-dom',
    globals: true,
    include: ['tests/**/*.{test,spec}.ts'],
    setupFiles: ['./tests/setup.ts'],
  },
  resolve: {
    alias: {
      '~': fileURLToPath(new URL('./src', import.meta.url)),
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
})
