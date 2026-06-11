<script setup lang="ts">
definePageMeta({ layout: 'bare', middleware: ['guest'] })

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
onMounted(restoreScroll)
</script>

<template>
  <div class="relative">
    <LandingBackdrop />

    <LandingHero />
    <LandingHeroVisual />
    <LandingSteps />
    <LandingFeatures />
    <LandingMetrics />
    <LandingPricing />
    <LandingCta />
    <LandingFooter />
  </div>
</template>

<style>
/* Scroll-reveal for below-the-fold sections. The class is added by the
   `v-reveal` directive (client only, skipped under reduced-motion); the media
   query is a fallback so motion is never forced. */
.reveal {
  opacity: 0;
  transform: translateY(16px);
  transition:
    opacity 0.6s cubic-bezier(0.22, 1, 0.36, 1),
    transform 0.6s cubic-bezier(0.22, 1, 0.36, 1);
}
.reveal-in {
  opacity: 1;
  transform: none;
}
@media (prefers-reduced-motion: reduce) {
  .reveal {
    opacity: 1 !important;
    transform: none !important;
    transition: none !important;
  }
}
</style>
