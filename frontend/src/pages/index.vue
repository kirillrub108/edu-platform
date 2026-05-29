<script setup lang="ts">
definePageMeta({ layout: 'bare', middleware: ['guest'] })

useSeoMeta({
  title: 'Edllm — Видеолекции из презентаций на нейросетях Yandex',
  description:
    'Загрузите PPTX — ИИ-модели Yandex проанализируют слайды, напишут скрипт и озвучат его синтезом речи Yandex SpeechKit. Готовое MP4 без съёмок и монтажа за минуты.',
  ogTitle: 'Edllm — Видеолекции из презентаций на ИИ Yandex',
  ogDescription:
    'PPTX → ИИ-анализ слайдов → озвучка Yandex SpeechKit → готовое MP4. Без студии и монтажа.',
  twitterCard: 'summary',
})

// The landing is reached only by anonymous visitors — the `guest` middleware
// redirects logged-in users to their dashboard — so all CTAs point at /register
// and /login directly.
onMounted(restoreScroll)
</script>

<template>
  <div class="relative">
    <!-- decorative background -->
    <div class="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
      <div class="absolute -top-40 -left-40 h-[480px] w-[480px] rounded-full bg-violet-200/40 blur-3xl"></div>
      <div class="absolute top-20 -right-32 h-[420px] w-[420px] rounded-full bg-fuchsia-200/40 blur-3xl"></div>
      <div
        class="absolute inset-0"
        style="background-image: radial-gradient(rgba(109,40,217,0.07) 1px, transparent 1px); background-size: 28px 28px;"
      ></div>
    </div>

    <LandingHero />
    <LandingSteps />
    <LandingFeatures />
    <LandingMetrics />
    <LandingCta />
    <LandingFooter />
  </div>
</template>
