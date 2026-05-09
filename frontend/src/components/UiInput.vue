<script setup lang="ts">
defineProps<{
  modelValue?: string
  label?: string
  error?: string
  hint?: string
  type?: string
  placeholder?: string
  as?: 'input' | 'textarea'
  rows?: number
}>()
defineEmits(['update:modelValue', 'blur'])
</script>

<template>
  <div class="space-y-1.5">
    <label v-if="label" class="block text-sm font-medium text-gray-700">{{ label }}</label>
    <component
      :is="as ?? 'input'"
      :type="type ?? 'text'"
      :value="modelValue"
      :placeholder="placeholder"
      :rows="rows"
      :class="[
        'w-full bg-white px-4 py-2.5 text-sm text-gray-900 transition',
        'border rounded-xl focus:outline-none focus:ring-2 focus:ring-violet-500/30',
        error
          ? 'border-rose-300 focus:border-rose-400'
          : 'border-gray-200 focus:border-violet-400',
        as === 'textarea' && 'resize-none',
      ]"
      @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
      @blur="$emit('blur')"
    />
    <p v-if="error" class="text-xs text-rose-600">{{ error }}</p>
    <p v-else-if="hint" class="text-xs text-gray-400">{{ hint }}</p>
  </div>
</template>
