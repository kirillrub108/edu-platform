<script setup lang="ts">
import { ref, watch } from 'vue'
import { LayoutDashboard, BarChart3, Sparkles, ChevronLeft, ChevronRight } from 'lucide-vue-next'

const STORAGE_KEY = 'sidebar:collapsed'
const isCollapsed = ref(
  typeof localStorage !== 'undefined'
    ? localStorage.getItem(STORAGE_KEY) === 'true'
    : false
)
watch(isCollapsed, (val) => localStorage.setItem(STORAGE_KEY, String(val)))

const items = [
  { to: '/dashboard',              label: 'Мои курсы',         icon: LayoutDashboard },
  { to: '/analytics/quiz-results', label: 'Результаты тестов', icon: BarChart3 },
]
</script>

<template>
  <aside
    class="hidden lg:flex flex-col shrink-0 bg-white border-r border-violet-100 h-[calc(100vh-64px)] sticky top-16 overflow-hidden transition-all duration-200"
    :class="isCollapsed ? 'w-14' : 'w-[260px]'"
  >
    <!-- Toggle button -->
    <div class="flex p-2" :class="isCollapsed ? 'justify-center' : 'justify-end'">
      <button
        @click="isCollapsed = !isCollapsed"
        class="p-1.5 rounded-lg hover:bg-violet-50 text-gray-400 hover:text-violet-600 transition"
        :title="isCollapsed ? 'Развернуть' : 'Свернуть'"
      >
        <ChevronLeft v-if="!isCollapsed" class="w-4 h-4" />
        <ChevronRight v-else class="w-4 h-4" />
      </button>
    </div>

    <!-- Nav -->
    <nav class="flex-1 overflow-y-auto px-2 flex flex-col gap-0.5">
      <NuxtLink
        v-for="it in items"
        :key="it.to"
        :to="it.to"
        class="flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium text-gray-600 hover:text-violet-700 hover:bg-violet-50 transition"
        :class="isCollapsed ? 'justify-center' : ''"
        active-class="!text-violet-700 !bg-violet-50"
        :title="isCollapsed ? it.label : undefined"
      >
        <component :is="it.icon" class="w-4 h-4 shrink-0" />
        <span v-show="!isCollapsed" class="whitespace-nowrap">{{ it.label }}</span>
      </NuxtLink>
    </nav>

    <!-- CTA — expanded -->
    <div
      v-if="!isCollapsed"
      class="m-4 p-4 rounded-2xl bg-gradient-to-br from-violet-600 to-purple-500 text-white"
    >
      <Sparkles class="w-5 h-5 mb-2" />
      <div class="text-sm font-semibold">Pro-режим</div>
      <div class="text-xs opacity-80 mt-1">HD-видео, GPT-4o vision и неограниченные курсы.</div>
      <button class="mt-3 w-full bg-white/15 hover:bg-white/25 rounded-lg py-1.5 text-xs font-medium transition">
        Подключить
      </button>
    </div>

    <!-- CTA — collapsed -->
    <div v-else class="flex justify-center pb-4">
      <button
        title="Pro-режим"
        class="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-600 to-purple-500 flex items-center justify-center hover:opacity-90 transition"
      >
        <Sparkles class="w-5 h-5 text-white" />
      </button>
    </div>
  </aside>
</template>
