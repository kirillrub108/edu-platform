// Yandex.Metrika counter id — single source of truth (public by nature: it is
// visible in the page HTML). Used both by the head snippet and runtimeConfig.
const METRIKA_ID = 110101429

// Official new-version (tag.js) loader. Must sit in the served HTML, not be
// injected after hydration, or Metrika's counter check can't find it on a SPA.
const METRIKA_SNIPPET = `(function(m,e,t,r,i,k,a){m[i]=m[i]||function(){(m[i].a=m[i].a||[]).push(arguments)};m[i].l=1*new Date();for(var j=0;j<document.scripts.length;j++){if(document.scripts[j].src===r){return}}k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a)})(window,document,"script","https://mc.yandex.ru/metrika/tag.js","ym");ym(${METRIKA_ID},"init",{defer:true,clickmap:true,trackLinks:true,accurateTrackBounce:true,webvisor:true});`

export default defineNuxtConfig({
  srcDir: 'src/',
  devtools: { enabled: false },
  modules: ['@nuxtjs/tailwindcss', '@pinia/nuxt'],
  // Hybrid rendering: SSG for landing, CSR for everything else
  routeRules: {
    // ssr: true is required here — without it, '/' would inherit ssr: false
    // from the '/**' wildcard rule below, and prerender would only emit an
    // empty SPA shell (no useSeoMeta output in the static HTML, which is why
    // Yandex/search bots saw no <meta description>).
    '/': { prerender: true, ssr: true },
    '/**': { ssr: false },
  },
  runtimeConfig: {
    public: {
      // Relative path so the Nitro devProxy below handles routing and cookies
      // are same-origin in development. Override via NUXT_PUBLIC_API_BASE in
      // production (e.g. http://backend:8000/api/v1 behind an nginx proxy).
      apiBase: '/api/v1',
      // Yandex.Metrika counter id. Empty → tracking is fully disabled; the real
      // id is injected by the $production block below, so dev never tracks.
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
      meta: [
        { charset: 'utf-8' },
        { name: 'viewport', content: 'width=device-width, initial-scale=1' },
        { name: 'yandex-verification', content: 'e0e49aa6b58443ab' },
      ],
      link: [
        { rel: 'icon', type: 'image/x-icon', href: '/favicon.ico' },
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
  // Production only: load the counter and enable hits/goals. In dev metrikaId
  // stays '' and the whole integration no-ops.
  $production: {
    runtimeConfig: { public: { metrikaId: String(METRIKA_ID) } },
    app: {
      head: {
        script: [{ innerHTML: METRIKA_SNIPPET, tagPosition: 'head' }],
        noscript: [
          {
            innerHTML: `<div><img src="https://mc.yandex.ru/watch/${METRIKA_ID}" style="position:absolute;left:-9999px" alt="" /></div>`,
            tagPosition: 'bodyClose',
          },
        ],
      },
    },
  },
  compatibilityDate: '2025-01-01',
})
