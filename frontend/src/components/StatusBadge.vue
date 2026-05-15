<script setup lang="ts">
import { computed } from 'vue'
import { Clock, Edit3, Loader2, CheckCircle2, AlertCircle, Sparkles, HelpCircle } from 'lucide-vue-next'

type KnownStatus = 'draft' | 'analyzing' | 'ready_for_edit' | 'processing' | 'published' | 'error'

const props = defineProps<{
  status: KnownStatus | (string & {})
}>()

const map: Record<KnownStatus, { label: string; icon: object; tone: string; iconClass: string }> = {
  draft:          { label: 'Черновик',       icon: Clock,        tone: 'bg-gray-100 text-gray-600',       iconClass: '' },
  analyzing:      { label: 'Анализируется',  icon: Sparkles,     tone: 'bg-violet-100 text-violet-700',   iconClass: 'animate-pulse' },
  ready_for_edit: { label: 'Готов к правке', icon: Edit3,        tone: 'bg-indigo-100 text-indigo-700',   iconClass: '' },
  processing:     { label: 'Генерируется',   icon: Loader2,      tone: 'bg-amber-100 text-amber-700',     iconClass: 'animate-spin' },
  published:      { label: 'Опубликован',    icon: CheckCircle2, tone: 'bg-emerald-100 text-emerald-700', iconClass: '' },
  error:          { label: 'Ошибка',         icon: AlertCircle,  tone: 'bg-rose-100 text-rose-700',       iconClass: '' },
}

const FALLBACK = { icon: HelpCircle, tone: 'bg-gray-100 text-gray-500', iconClass: '' }

// snake_case / kebab-case → "Title Case"
function humanize(s: string) {
  return s.replace(/[-_]+/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

const entry = computed(() => {
  const s = props.status
  if (!s) return { ...FALLBACK, label: '—' }
  const known = map[s as KnownStatus]
  if (known) return known
  return { ...FALLBACK, label: humanize(s) }
})
</script>

<template>
  <span
    :class="['inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium', entry.tone]"
  >
    <component :is="entry.icon" class="w-3.5 h-3.5" :class="entry.iconClass" />
    {{ entry.label }}
  </span>
</template>
