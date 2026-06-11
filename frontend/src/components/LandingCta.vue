<script setup lang="ts">
import { ArrowRight } from 'lucide-vue-next'
</script>

<template>
  <section class="px-6 py-20 max-w-4xl mx-auto">
    <div class="relative overflow-hidden rounded-3xl border border-violet-100 bg-white p-10 md:p-14 text-center shadow-soft">
      <div class="pointer-events-none absolute -top-24 left-1/2 h-64 w-64 -translate-x-1/2 rounded-full bg-violet-200/40 blur-3xl"></div>
      <div class="relative">
        <h2 class="text-2xl md:text-3xl font-semibold tracking-tight">
          Превратите презентацию в видеокурс уже сегодня
        </h2>
        <p class="mt-3 max-w-xl mx-auto text-gray-600">
          Загрузите PPTX и получите озвученную видеолекцию — ИИ соберёт её без съёмок и монтажа.
        </p>
        <div class="mt-8 flex flex-col sm:flex-row gap-3 justify-center">
          <NuxtLink to="/register">
            <UiButton variant="primary" size="lg">
              Создать аккаунт
              <template #icon><ArrowRight class="w-4 h-4 order-last" /></template>
            </UiButton>
          </NuxtLink>
          <NuxtLink to="/login">
            <UiButton variant="secondary" size="lg">Войти</UiButton>
          </NuxtLink>
        </div>
      </div>
    </div>
  </section>
</template>
