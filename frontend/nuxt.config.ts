export default defineNuxtConfig({
  srcDir: 'src/',
  devtools: { enabled: true },
  modules: ['@nuxtjs/tailwindcss', '@pinia/nuxt'],
  // Hybrid rendering: SSG for landing, CSR for everything else
  routeRules: {
    '/': { prerender: true },
    '/**': { ssr: false },
  },
  runtimeConfig: {
    public: {
      apiBase: process.env.NUXT_PUBLIC_API_BASE || 'http://localhost:8000/api/v1',
    },
  },
  app: {
    head: {
      title: 'EduAI',
      meta: [{ charset: 'utf-8' }, { name: 'viewport', content: 'width=device-width, initial-scale=1' }],
      link: [
        { rel: 'preconnect', href: 'https://fonts.googleapis.com' },
        { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossorigin: '' },
        {
          rel: 'stylesheet',
          href: 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap',
        },
      ],
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
