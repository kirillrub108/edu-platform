<script setup lang="ts">
import { Check, Loader2 } from 'lucide-vue-next'

defineProps<{
  stages: { label: string; pct?: number }[]
  current: number
}>()
</script>

<template>
  <ol class="flex items-start">
    <li v-for="(s, i) in stages" :key="i" class="flex-1 flex flex-col items-center relative">
      <div
        v-if="i > 0"
        class="absolute top-5 right-1/2 left-[-50%] h-0.5"
        :class="i <= current ? 'bg-violet-500' : 'bg-gray-200'"
      ></div>
      <div
        class="relative z-10 w-10 h-10 rounded-full grid place-items-center text-sm font-medium"
        :class="[
          i < current ? 'bg-violet-600 text-white' :
          i === current ? 'bg-white text-violet-700 ring-4 ring-violet-200 animate-pulse' :
          'bg-white text-gray-400 border border-gray-300'
        ]"
      >
        <Check v-if="i < current" class="w-4 h-4" />
        <Loader2 v-else-if="i === current" class="w-4 h-4 animate-spin" />
        <span v-else>{{ i + 1 }}</span>
      </div>
      <div
        class="mt-2 text-[11px] text-center"
        :class="i === current ? 'text-violet-700 font-medium' : 'text-gray-500'"
      >
        {{ s.label }}
      </div>
    </li>
  </ol>
</template>
