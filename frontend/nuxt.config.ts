export default defineNuxtConfig({
  srcDir: 'src/',
  ssr: false,
  devtools: { enabled: true },
  modules: ['@nuxtjs/tailwindcss'],
  runtimeConfig: {
    public: {
      apiBase: process.env.NUXT_PUBLIC_API_BASE || 'http://localhost:8000/api/v1',
    },
  },
  app: {
    head: {
      title: 'Edu Platform',
      meta: [{ charset: 'utf-8' }, { name: 'viewport', content: 'width=device-width, initial-scale=1' }],
    },
  },
  vite: {
    server: {
      watch: {
        usePolling: true,
        interval: 500,
      },
      hmr: {
        protocol: 'ws',
        host: '0.0.0.0',
        clientPort: 3000,
      },
    },
  },
  // viteEnvironmentApi makes Nuxt set NUXT_VITE_NODE_OPTIONS immediately in configureServer
  // (before Nitro worker starts), instead of waiting for the SSR vite server hook that never
  // fires when ssr:false — which is the root cause of "Vite Node IPC socket path not configured"
  experimental: {
    viteEnvironmentApi: true,
  },
  compatibilityDate: '2025-01-01',
})
