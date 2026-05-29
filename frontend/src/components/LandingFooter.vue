<script setup lang="ts">
import { GraduationCap } from 'lucide-vue-next'

const year = new Date().getFullYear()
</script>

<template>
  <footer class="border-t border-violet-100 bg-white/60">
    <div class="px-6 py-10 max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-6">
      <div class="flex items-center gap-2.5">
        <div class="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-violet-600 to-purple-500 shadow-sm">
          <GraduationCap class="h-5 w-5 text-white" />
        </div>
        <div class="leading-tight">
          <div class="bg-gradient-to-r from-violet-600 to-purple-500 bg-clip-text text-lg font-semibold text-transparent">
            Edllm
          </div>
          <div class="text-xs text-gray-500">Видеолекции из презентаций на ИИ Yandex</div>
        </div>
      </div>

      <nav class="flex items-center gap-6 text-sm text-gray-600">
        <NuxtLink to="/login" class="transition-colors hover:text-violet-700">Войти</NuxtLink>
        <NuxtLink to="/register" class="transition-colors hover:text-violet-700">Регистрация</NuxtLink>
      </nav>

      <div class="text-xs text-gray-400">© {{ year }} Edllm</div>
    </div>
  </footer>
</template>
