<script setup lang="ts">
import { Zap, Clock, Monitor, Sparkles } from 'lucide-vue-next'

const vReveal = useScrollReveal()

// Static placeholders describing the product capability — no client/usage claims.
const metrics = [
  { icon: Clock, value: '2–5 мин', label: 'на сборку одной видеолекции' },
  { icon: Zap, value: '10×', label: 'экономия времени против ручной записи' },
  { icon: Monitor, value: '1080p', label: 'HD-видео с синхронной озвучкой' },
  { icon: Sparkles, value: 'PPTX → MP4', label: 'полностью автоматический конвейер' },
]
</script>

<template>
  <section class="px-6 py-12 max-w-5xl mx-auto">
    <div
      v-reveal
      class="relative overflow-hidden rounded-3xl bg-gradient-to-br from-violet-700 via-violet-600 to-indigo-600 p-8 md:p-10 text-white shadow-hero"
    >
      <div aria-hidden="true" class="banner-sheen pointer-events-none absolute inset-0"></div>
      <p class="relative text-center text-sm font-medium text-white/70">
        Создано для преподавателей, методистов и онлайн-школ
      </p>
      <div class="relative mt-8 grid grid-cols-2 lg:grid-cols-4 gap-8">
        <div v-for="(m, i) in metrics" :key="i" class="text-center">
          <div class="mx-auto mb-3 grid h-11 w-11 place-items-center rounded-xl bg-white/15">
            <component :is="m.icon" class="h-5 w-5" />
          </div>
          <div class="text-2xl md:text-3xl font-semibold leading-none tabular-nums">{{ m.value }}</div>
          <div class="mt-1.5 text-xs text-white/75 leading-snug">{{ m.label }}</div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
/* Slow diagonal sheen gliding across the saturated violet stats banner. Sits
   behind the numbers (which get `relative`); low-opacity white, no contrast hit. */
.banner-sheen {
  background: linear-gradient(
    115deg,
    transparent 30%,
    rgba(255, 255, 255, 0.12) 48%,
    rgba(255, 255, 255, 0.18) 50%,
    rgba(255, 255, 255, 0.12) 52%,
    transparent 70%
  );
  background-size: 250% 100%;
  animation: banner-sheen 9s ease-in-out infinite;
}
@keyframes banner-sheen {
  0% { background-position: 150% 0; }
  100% { background-position: -150% 0; }
}
@media (prefers-reduced-motion: reduce) {
  .banner-sheen {
    animation: none;
    opacity: 0;
  }
}
</style>
