<script setup lang="ts">
import { Eye, EyeOff } from 'lucide-vue-next'

const props = defineProps<{
  modelValue?: string
  label?: string
  /** Shows a muted "необязательно" badge next to the label. */
  optional?: boolean
  error?: string
  hint?: string
  type?: string
  placeholder?: string
  as?: 'input' | 'textarea'
  rows?: number
  maxlength?: number
}>()
defineEmits(['update:modelValue', 'blur'])

// Password fields get a built-in show/hide toggle everywhere they're used.
const revealed = ref(false)
const isPassword = computed(() => props.type === 'password')
const inputType = computed(() => (isPassword.value && revealed.value ? 'text' : (props.type ?? 'text')))
</script>

<template>
  <div class="space-y-1.5">
    <div v-if="label" class="flex items-baseline gap-1.5">
      <label class="block text-sm font-medium text-gray-700">{{ label }}</label>
      <span v-if="optional" class="text-xs font-normal text-gray-400">необязательно</span>
    </div>
    <div class="relative">
      <component
        :is="as ?? 'input'"
        :type="inputType"
        :value="modelValue"
        :placeholder="placeholder"
        :rows="rows"
        :maxlength="maxlength"
        :class="[
          'w-full bg-white px-4 py-2.5 text-sm text-gray-900 transition',
          'border rounded-xl focus:outline-none focus:ring-2 focus:ring-violet-500/30',
          error
            ? 'border-rose-300 focus:border-rose-400'
            : 'border-gray-200 focus:border-violet-400',
          as === 'textarea' && 'resize-none',
          isPassword && 'pr-10',
        ]"
        @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
        @blur="$emit('blur')"
      />
      <button
        v-if="isPassword"
        type="button"
        class="absolute inset-y-0 right-0 flex items-center px-3 text-gray-400 transition hover:text-gray-600"
        :aria-label="revealed ? 'Скрыть пароль' : 'Показать пароль'"
        @click="revealed = !revealed"
      >
        <EyeOff v-if="revealed" class="h-4 w-4" />
        <Eye v-else class="h-4 w-4" />
      </button>
    </div>
    <p v-if="error" class="text-xs text-rose-600">{{ error }}</p>
    <p v-else-if="hint" class="text-xs text-gray-500">{{ hint }}</p>
  </div>
</template>
