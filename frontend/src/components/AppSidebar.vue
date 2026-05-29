<script setup lang="ts">
import { ref, watch } from 'vue'
import { LayoutDashboard, BarChart3, Wallet, ChevronLeft, ChevronRight } from 'lucide-vue-next'

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
  { to: '/billing',                label: 'Баланс',            icon: Wallet },
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

    <!-- Credit balance — expanded -->
    <div v-if="!isCollapsed" class="m-4">
      <CreditBalanceWidget />
    </div>

    <!-- Credit balance — collapsed -->
    <div v-else class="flex justify-center pb-4">
      <CreditBalanceWidget collapsed />
    </div>
  </aside>
</template>
