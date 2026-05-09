<script setup lang="ts">
import { LayoutDashboard, BookOpen, Sparkles } from 'lucide-vue-next'

const items = [
  { to: '/dashboard', label: 'Дашборд', icon: LayoutDashboard },
  { to: '/courses',   label: 'Мои курсы', icon: BookOpen },
]
</script>

<template>
  <aside
    class="hidden lg:flex flex-col w-[260px] shrink-0 bg-white border-r border-violet-100 min-h-[calc(100vh-64px)] sticky top-16"
  >
    <nav class="p-4 flex flex-col gap-0.5">
      <NuxtLink
        v-for="it in items"
        :key="it.to"
        :to="it.to"
        class="flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium text-gray-600 hover:text-violet-700 hover:bg-violet-50 transition border-l-2 border-transparent"
        active-class="!text-violet-700 !bg-violet-50 !border-violet-600"
      >
        <component :is="it.icon" class="w-4 h-4" />
        {{ it.label }}
      </NuxtLink>
    </nav>
    <div class="mt-auto m-4 p-4 rounded-2xl bg-gradient-to-br from-violet-600 to-purple-500 text-white">
      <Sparkles class="w-5 h-5 mb-2" />
      <div class="text-sm font-semibold">Pro-режим</div>
      <div class="text-xs opacity-80 mt-1">HD-видео, GPT-4o vision и неограниченные курсы.</div>
      <button class="mt-3 w-full bg-white/15 hover:bg-white/25 rounded-lg py-1.5 text-xs font-medium transition">
        Подключить
      </button>
    </div>
  </aside>
</template>
