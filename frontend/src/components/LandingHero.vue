<script setup lang="ts">
import { ArrowRight, Play } from 'lucide-vue-next'
</script>

<template>
  <section class="px-6 pt-20 pb-16 lg:pt-28 lg:pb-20 max-w-5xl mx-auto text-center">
    <h1 class="text-4xl md:text-6xl font-semibold tracking-tight leading-[1.05]">
      Видеолекции из презентаций<br />
      <span class="bg-gradient-to-r from-violet-700 to-indigo-600 bg-clip-text text-transparent">
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
