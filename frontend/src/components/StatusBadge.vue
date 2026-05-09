<script setup lang="ts">
import { Clock, Edit3, Loader2, CheckCircle2, AlertCircle, Sparkles } from 'lucide-vue-next'

defineProps<{
  status: 'draft' | 'analyzing' | 'ready_for_edit' | 'processing' | 'published' | 'error'
}>()

const map = {
  draft:          { label: 'Черновик',       icon: Clock,        tone: 'bg-gray-100 text-gray-600',       iconClass: '' },
  analyzing:      { label: 'Анализируется',  icon: Sparkles,     tone: 'bg-violet-100 text-violet-700',   iconClass: 'animate-pulse' },
  ready_for_edit: { label: 'Готов к правке', icon: Edit3,        tone: 'bg-indigo-100 text-indigo-700',   iconClass: '' },
  processing:     { label: 'Генерируется',   icon: Loader2,      tone: 'bg-amber-100 text-amber-700',     iconClass: 'animate-spin' },
  published:      { label: 'Опубликован',    icon: CheckCircle2, tone: 'bg-emerald-100 text-emerald-700', iconClass: '' },
  error:          { label: 'Ошибка',         icon: AlertCircle,  tone: 'bg-rose-100 text-rose-700',       iconClass: '' },
} as const
</script>

<template>
  <span
    :class="['inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium', map[status].tone]"
  >
    <component :is="map[status].icon" class="w-3.5 h-3.5" :class="map[status].iconClass" />
    {{ map[status].label }}
  </span>
</template>
