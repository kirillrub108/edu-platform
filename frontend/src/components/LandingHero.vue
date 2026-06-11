<script setup lang="ts">
import { ArrowRight, Play } from 'lucide-vue-next'
</script>

<template>
  <section class="px-6 pt-20 pb-16 lg:pt-28 lg:pb-20 max-w-5xl mx-auto text-center">
    <h1 class="text-4xl md:text-6xl font-semibold tracking-tight leading-[1.05]">
      Видеолекции из презентаций<br />
      <span class="accent-sweep bg-clip-text text-transparent">
        за минуты, а не часы
      </span>
    </h1>

    <p class="mt-6 max-w-2xl mx-auto text-lg text-gray-600 leading-relaxed">
      Загрузите презентацию — ИИ проанализирует слайды, напишет закадровый текст
      и озвучит его <span class="font-medium text-gray-800">нейросетевым синтезом речи</span>.
      На выходе — готовое MP4 без съёмок и монтажа.
    </p>

    <div class="mt-9 flex flex-col sm:flex-row gap-3 justify-center">
      <NuxtLink to="/register">
        <UiButton variant="primary" size="lg">
          Создать аккаунт
          <template #icon><ArrowRight class="w-4 h-4 order-last" /></template>
        </UiButton>
      </NuxtLink>
      <NuxtLink to="/login">
        <UiButton variant="secondary" size="lg">
          <template #icon><Play class="w-4 h-4" /></template>
          Войти
        </UiButton>
      </NuxtLink>
    </div>

    <p class="mt-6 text-xs text-gray-500">
      Без съёмочной студии и монтажа · 4–8 часов работы превращаются в 2–5 минут
    </p>
  </section>
</template>

<style scoped>
/* Slow violet→indigo→fuchsia sweep across the headline accent. Animates only the
   text-clipped gradient fill; the rest pose (position 0%) lands on brand violet,
   matching the original static gradient under reduced motion. */
.accent-sweep {
  background-image: linear-gradient(100deg, #6d28d9 0%, #4f46e5 25%, #a855f7 50%, #4f46e5 75%, #6d28d9 100%);
  background-size: 220% 100%;
  background-position: 0% 0;
  animation: accent-sweep 7s ease-in-out infinite;
}
@keyframes accent-sweep {
  0%, 100% { background-position: 0% 0; }
  50% { background-position: 100% 0; }
}
@media (prefers-reduced-motion: reduce) {
  .accent-sweep {
    animation: none;
    background-position: 0% 0;
  }
}
</style>
