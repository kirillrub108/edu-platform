<script setup lang="ts">
// Pixel rebuild of design_handoff_edllm. The whole landing lives under a single
// `.ldg` root so the design's namespaced stylesheet (assets/landing.css) applies
// without leaking generic class names into the rest of the app. We opt out of the
// app layout (no AppHeader) — the landing ships its own LandingNav.
//
// CSS + the Manrope webfont are loaded here at the page level (not in
// nuxt.config) so they ship only with the landing route AND so they hot-reload
// in dev — only `src/` is bind-mounted into the frontend container; nuxt.config
// is image-baked, so config edits would need a rebuild to take effect.
import '~/assets/landing.css'

definePageMeta({ layout: false, middleware: ['guest'] })

useHead({
  link: [
    {
      rel: 'stylesheet',
      href: 'https://fonts.googleapis.com/css2?family=Manrope:wght@500;600;700;800&display=swap',
    },
  ],
})

useSeoMeta({
  title: 'Edllm — Видеолекции из презентаций за минуты',
  description:
    'Загрузите PPTX — ИИ проанализирует слайды, напишет закадровый текст и озвучит его нейросетевым синтезом речи. Готовое MP4 без съёмок и монтажа за минуты.',
  ogTitle: 'Edllm — Видеолекции из презентаций на ИИ',
  ogDescription:
    'PPTX → ИИ-анализ слайдов → нейросетевая озвучка → готовое MP4. Без студии и монтажа.',
  twitterCard: 'summary',
})

// The landing is reached only by anonymous visitors — the `guest` middleware
// redirects logged-in users to their dashboard — so all CTAs point at /register
// and /login directly.
const ldg = ref<HTMLElement | null>(null)
useLandingMotion(ldg)

onMounted(restoreScroll)
</script>

<template>
  <div ref="ldg" class="ldg">
    <LandingBackdrop />
    <LandingNav />

    <main id="top">
      <LandingHero />
      <LandingSteps />
      <LandingFeatures />
      <LandingMetrics />
      <LandingPricing />
      <LandingCta />
    </main>

    <LandingFooter />
  </div>
</template>
