<script setup lang="ts">
import type { LucideIcon } from 'lucide-vue-next'

defineProps<{
  label: string
  value: string
  icon: LucideIcon
  // Full literal Tailwind classes for the icon chip (e.g. 'bg-violet-100
  // text-violet-600'). Passed verbatim so the JIT compiler can see them.
  chip: string
  subtitle?: string
}>()
</script>

<template>
  <div class="bg-white rounded-2xl border border-gray-100 p-5 flex items-start gap-4">
    <div
      class="w-11 h-11 rounded-xl flex items-center justify-center flex-shrink-0"
      :class="chip"
    >
      <component :is="icon" class="w-5 h-5" />
    </div>
    <div class="min-w-0">
      <div class="text-sm text-gray-500">{{ label }}</div>
      <div class="text-2xl font-semibold text-gray-900 mt-0.5 truncate">{{ value }}</div>
      <div v-if="subtitle" class="text-xs text-gray-400 mt-0.5 truncate">{{ subtitle }}</div>
    </div>
  </div>
</template>
