<script setup lang="ts">
import { ChevronLeft } from 'lucide-vue-next'

defineProps<{
  title: string
  status: string
}>()
</script>

<template>
  <div>
    <NuxtLink
      to="/dashboard"
      class="inline-flex items-center gap-1 text-sm text-violet-700 hover:text-violet-600 font-medium transition mb-2"
    >
      <ChevronLeft class="w-4 h-4" />
      Назад к курсам
    </NuxtLink>
    <div class="flex items-center gap-3 flex-wrap">
      <h1 class="text-2xl font-semibold text-gray-900">{{ title }}</h1>
      <StatusBadge :status="status" />
    </div>
  </div>
</template>
