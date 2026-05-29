<script setup lang="ts">
import { ArrowRight, Play } from 'lucide-vue-next'
</script>

<template>
  <section class="px-6 pt-20 pb-16 lg:pt-28 lg:pb-20 max-w-5xl mx-auto text-center">
    <div
      class="inline-flex items-center gap-2 rounded-full border border-violet-100 bg-white/70 px-3.5 py-1.5 text-xs font-medium text-gray-600 shadow-soft backdrop-blur"
    >
      <span class="relative flex h-2 w-2">
        <span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-500 opacity-60"></span>
        <span class="relative inline-flex h-2 w-2 rounded-full bg-red-500"></span>
      </span>
      На базе нейросетей Yandex
    </div>

    <h1 class="mt-6 text-4xl md:text-6xl font-semibold tracking-tight leading-[1.05]">
      Видеолекции из презентаций<br />
      <span class="bg-gradient-to-r from-violet-600 via-purple-500 to-fuchsia-500 bg-clip-text text-transparent">
        за минуты, а не часы
      </span>
    </h1>

    <p class="mt-6 max-w-2xl mx-auto text-lg text-gray-600 leading-relaxed">
      Загрузите презентацию. Платформа проанализирует слайды новейшими ИИ-моделями
      Yandex, напишет скрипт и озвучит его синтезом речи
      <span class="font-medium text-gray-800">Yandex SpeechKit</span>. На выходе — готовое MP4.
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
