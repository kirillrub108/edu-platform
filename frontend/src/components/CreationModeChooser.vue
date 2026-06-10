<script setup lang="ts">
import { Check } from 'lucide-vue-next'
import { CREATION_MODE_CARDS, type CreationModeValue } from '~/composables/useCreationMode'

const props = defineProps<{
  modelValue?: CreationModeValue | null
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: CreationModeValue): void
  (e: 'select', value: CreationModeValue): void
}>()

const choose = (mode: CreationModeValue, available: boolean) => {
  if (!available) return
  emit('update:modelValue', mode)
  emit('select', mode)
}
</script>

<template>
  <div>
    <h2 class="text-lg font-semibold text-gray-900 mb-1">Как создать урок?</h2>
    <p class="text-sm text-gray-500 mb-5">
      Выберите способ генерации контента — это определит дальнейший флоу.
    </p>

    <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
      <button
        v-for="card in CREATION_MODE_CARDS"
        :key="card.value"
        type="button"
        :disabled="!card.available"
        :class="[
          'relative text-left p-5 rounded-2xl border-2 transition-all duration-150 ease-out',
          card.value === 'video_upload' ? 'col-span-full' : '',
          card.available
            ? 'cursor-pointer'
            : 'opacity-60 cursor-not-allowed',
          props.modelValue === card.value
            ? 'border-violet-600 bg-violet-50 shadow-[0_4px_24px_rgba(109,40,217,0.12)]'
            : 'border-gray-200 bg-white hover:border-violet-200 hover:bg-violet-50/40',
        ]"
        @click="choose(card.value, card.available)"
      >
        <span
          v-if="!card.available"
          class="absolute top-4 right-4 text-[10px] uppercase tracking-wide font-semibold bg-gray-200 text-gray-600 px-2 py-0.5 rounded-full"
        >
          В разработке
        </span>
        <div
          v-else-if="props.modelValue === card.value"
          class="absolute top-4 right-4 w-6 h-6 rounded-full bg-violet-600 grid place-items-center"
        >
          <Check class="w-3.5 h-3.5 text-white" />
        </div>

        <div
          class="w-11 h-11 rounded-xl bg-gradient-to-br from-violet-500 to-purple-500 grid place-items-center mb-3 shadow-sm text-white text-lg"
        >
          {{ card.emoji }}
        </div>

        <div class="font-semibold text-gray-900">{{ card.title }}</div>
        <div class="text-xs text-violet-700 font-medium mb-2">{{ card.subtitle }}</div>
        <p class="text-sm text-gray-600 leading-relaxed">{{ card.description }}</p>
      </button>
    </div>
  </div>
</template>
