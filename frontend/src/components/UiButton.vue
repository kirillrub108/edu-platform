<script setup lang="ts">
import { Loader2 } from 'lucide-vue-next'

withDefaults(
  defineProps<{
    variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
    size?: 'sm' | 'md' | 'lg'
    loading?: boolean
    disabled?: boolean
    block?: boolean
    type?: 'button' | 'submit' | 'reset'
  }>(),
  { variant: 'primary', size: 'md', loading: false, disabled: false, block: false, type: 'button' },
)

const variants = {
  primary:   'bg-brand-gradient text-white shadow-soft hover:shadow-soft-hover hover:brightness-110 active:brightness-95',
  secondary: 'border border-violet-200 text-violet-700 hover:bg-violet-50 active:bg-violet-100 bg-white',
  ghost:     'hover:bg-gray-100 text-gray-600 active:bg-gray-200',
  danger:    'bg-rose-600 hover:bg-rose-500 text-white shadow-sm',
}
const sizes = {
  sm: 'text-sm px-3 py-1.5 rounded-lg',
  md: 'text-sm px-5 py-2.5 rounded-xl font-medium',
  lg: 'text-base px-6 py-3 rounded-xl font-medium',
}
</script>

<template>
  <button
    :type="type"
    :disabled="disabled || loading"
    :class="[
      'inline-flex items-center justify-center gap-2 transition-all duration-150 ease-out',
      'focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:ring-offset-1',
      'active:scale-[0.97]',
      variants[variant], sizes[size],
      block && 'w-full',
      (disabled || loading) && 'opacity-40 cursor-not-allowed active:scale-100',
    ]"
  >
    <Loader2 v-if="loading" class="w-4 h-4 animate-spin" />
    <slot v-else name="icon" />
    <slot />
  </button>
</template>
