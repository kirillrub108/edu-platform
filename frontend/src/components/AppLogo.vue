<script setup lang="ts">
import { GraduationCap } from 'lucide-vue-next'

// Single source for the Edllm logo across the app shell and auth pages:
// gradient mark (brand ramp) + dark wordmark, matching the landing's brand.
withDefaults(
  defineProps<{ withText?: boolean; size?: 'md' | 'lg' }>(),
  { withText: true, size: 'md' },
)

const marks = {
  md: 'w-9 h-9 rounded-xl',
  lg: 'h-12 w-12 rounded-2xl',
}
const icons = { md: 'w-5 h-5', lg: 'h-6 w-6' }
</script>

<template>
  <span class="inline-flex items-center gap-2.5">
    <span :class="['bg-brand-gradient grid place-items-center shadow-sm', marks[size]]">
      <GraduationCap :class="['text-white', icons[size]]" />
    </span>
    <span v-if="withText" class="font-semibold text-lg text-gray-900">Edllm</span>
  </span>
</template>
