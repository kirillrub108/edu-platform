<script setup lang="ts">
import { GraduationCap, ArrowUpRight } from 'lucide-vue-next'

const year = new Date().getFullYear()

const nav = {
  product: [
    { label: 'Как это работает', href: '#how' },
    { label: 'Возможности', href: '#features' },
  ],
  account: [
    { label: 'Создать аккаунт', to: '/register' },
    { label: 'Войти', to: '/login' },
  ],
}
</script>

<template>
  <footer class="relative overflow-hidden border-t border-violet-100 bg-gradient-to-b from-white to-violet-50/50">
    <!-- decorative glow -->
    <div class="pointer-events-none absolute -top-24 left-1/2 h-48 w-[640px] -translate-x-1/2 rounded-full bg-violet-300/20 blur-3xl"></div>

    <div class="relative mx-auto max-w-6xl px-6 py-14">
      <div class="grid grid-cols-2 gap-10 md:grid-cols-[1.6fr_1fr_1fr]">
        <!-- brand -->
        <div class="col-span-2 md:col-span-1">
          <NuxtLink to="/" class="inline-flex items-center gap-2.5">
            <div class="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-violet-600 to-purple-500 shadow-sm">
              <GraduationCap class="h-5 w-5 text-white" />
            </div>
            <span class="bg-gradient-to-r from-violet-600 to-purple-500 bg-clip-text text-lg font-semibold text-transparent">
              Edllm
            </span>
          </NuxtLink>
          <p class="mt-4 max-w-xs text-sm leading-relaxed text-gray-500">
            Превращаем презентации в озвученные видеолекции автоматически — на нейросетях Yandex.
          </p>
          <div class="mt-5 inline-flex items-center gap-2 rounded-full border border-violet-100 bg-white px-3 py-1.5 text-xs font-medium text-gray-600 shadow-soft">
            <span class="relative flex h-2 w-2">
              <span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-500 opacity-60"></span>
              <span class="relative inline-flex h-2 w-2 rounded-full bg-red-500"></span>
            </span>
            Работает на ИИ Yandex и SpeechKit
          </div>
        </div>

        <!-- product nav -->
        <nav aria-label="Продукт">
          <h3 class="text-xs font-semibold uppercase tracking-wider text-gray-400">Продукт</h3>
          <ul class="mt-4 space-y-3">
            <li v-for="item in nav.product" :key="item.href">
              <a :href="item.href" class="text-sm text-gray-600 transition-colors hover:text-violet-700">
                {{ item.label }}
              </a>
            </li>
          </ul>
        </nav>

        <!-- account nav -->
        <nav aria-label="Аккаунт">
          <h3 class="text-xs font-semibold uppercase tracking-wider text-gray-400">Аккаунт</h3>
          <ul class="mt-4 space-y-3">
            <li v-for="item in nav.account" :key="item.to">
              <NuxtLink
                :to="item.to"
                class="group inline-flex items-center gap-1 text-sm text-gray-600 transition-colors hover:text-violet-700"
              >
                {{ item.label }}
                <ArrowUpRight class="h-3.5 w-3.5 opacity-0 transition-opacity group-hover:opacity-100" />
              </NuxtLink>
            </li>
          </ul>
        </nav>
      </div>

      <!-- bottom bar -->
      <div class="mt-12 flex flex-col items-center justify-between gap-3 border-t border-violet-100 pt-6 sm:flex-row">
        <p class="text-xs text-gray-400">© {{ year }} Edllm. Все права защищены.</p>
        <p class="text-xs text-gray-400">PPTX → MP4 · нейросетевая озвучка Yandex SpeechKit</p>
      </div>
    </div>
  </footer>
</template>
