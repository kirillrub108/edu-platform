<script setup lang="ts">
import { computed } from 'vue'

// Russian labels + tones for submission statuses (StatusBadge only knows the
// lesson statuses and would humanize these to English).
const props = defineProps<{ status: string }>()

const MAP: Record<string, { label: string; tone: string }> = {
  not_started: { label: 'Не начато', tone: 'bg-gray-100 text-gray-500' },
  draft: { label: 'Черновик', tone: 'bg-gray-100 text-gray-600' },
  submitted: { label: 'Сдано', tone: 'bg-amber-100 text-amber-700' },
  graded: { label: 'Проверено', tone: 'bg-indigo-100 text-indigo-700' },
  returned: { label: 'Возвращено', tone: 'bg-emerald-100 text-emerald-700' },
}

const entry = computed(() => MAP[props.status] ?? MAP.not_started)
</script>

<template>
  <span
    :class="['inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium', entry.tone]"
  >
    {{ entry.label }}
  </span>
</template>
