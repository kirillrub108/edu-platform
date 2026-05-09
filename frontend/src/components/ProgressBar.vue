<script setup lang="ts">
defineProps<{ value?: number; total?: number; label?: string; indeterminate?: boolean }>()
</script>

<template>
  <div>
    <div v-if="label" class="flex justify-between text-sm text-violet-700 mb-2">
      <span>{{ label }}</span>
      <span v-if="!indeterminate && total" class="text-gray-500">{{ value }} / {{ total }}</span>
    </div>
    <div class="h-2 rounded-full bg-violet-100 overflow-hidden relative">
      <div
        v-if="!indeterminate"
        class="h-full bg-gradient-to-r from-violet-500 to-purple-500 transition-all duration-500 relative"
        :style="{ width: ((value ?? 0) / (total ?? 1) * 100) + '%' }"
      >
        <div class="absolute inset-0 bg-[linear-gradient(90deg,transparent,rgba(255,255,255,.55),transparent)] bg-[length:200%_100%] animate-shimmer"></div>
      </div>
      <div
        v-else
        class="absolute h-full w-1/3 bg-gradient-to-r from-violet-500 to-purple-500 rounded-full animate-indeterminate"
      ></div>
    </div>
  </div>
</template>
