export default defineNuxtConfig({
  srcDir: 'src/',
  devtools: { enabled: false },
  modules: ['@nuxtjs/tailwindcss', '@pinia/nuxt'],
  // Hybrid rendering: SSG for landing, CSR for everything else
  routeRules: {
    '/': { prerender: true },
    '/**': { ssr: false },
  },
  runtimeConfig: {
    public: {
      // Relative path so the Nitro devProxy below handles routing and cookies
      // are same-origin in development. Override via NUXT_PUBLIC_API_BASE in
      // production (e.g. http://backend:8000/api/v1 behind an nginx proxy).
      apiBase: '/api/v1',
      // Yandex.Metrika counter id. Empty → tracking is fully disabled (dev/test).
      // Set the real id only in prod via NUXT_PUBLIC_METRIKA_ID — never commit it.
      metrikaId: '',
    },
  },
  nitro: {
    devProxy: {
      // Proxy /api/* to the backend so frontend and backend share the same
      // origin in dev — required for SameSite=Lax httpOnly cookies to work
      // without COOKIE_SECURE=true.
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  app: {
    head: {
      title: 'Edllm',
      meta: [{ charset: 'utf-8' }, { name: 'viewport', content: 'width=device-width, initial-scale=1' }],
      link: [
        { rel: 'icon', type: 'image/x-icon', href: '/icons/favicon.ico' },
        { rel: 'icon', type: 'image/png', sizes: '16x16', href: '/icons/favicon-16x16.png' },
        { rel: 'icon', type: 'image/png', sizes: '32x32', href: '/icons/favicon-32x32.png' },
        { rel: 'apple-touch-icon', sizes: '180x180', href: '/icons/apple-touch-icon.png' },
        { rel: 'manifest', href: '/site.webmanifest' },
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
