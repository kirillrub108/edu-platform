<script setup lang="ts">
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
    <h2 class="text-lg font-semibold mb-1">Как создать урок?</h2>
    <p class="text-sm text-gray-500 mb-5">Выберите способ генерации контента — это определит дальнейший флоу.</p>

    <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
      <button
        v-for="card in CREATION_MODE_CARDS"
        :key="card.value"
        type="button"
        :disabled="!card.available"
        :class="[
          'group relative text-left bg-white border rounded-xl p-5 transition',
          card.available
            ? 'hover:border-brand hover:shadow-md hover:-translate-y-0.5 cursor-pointer'
            : 'opacity-60 cursor-not-allowed',
          props.modelValue === card.value ? 'border-brand ring-2 ring-brand/30' : 'border-gray-200',
        ]"
        @click="choose(card.value, card.available)"
      >
        <span
          v-if="!card.available"
          class="absolute top-3 right-3 text-[10px] uppercase tracking-wide bg-gray-200 text-gray-600 px-2 py-0.5 rounded-full font-semibold"
        >
          В разработке
        </span>

        <div class="flex items-start gap-3 mb-3">
          <div class="text-3xl leading-none mt-0.5">{{ card.emoji }}</div>
          <div>
            <div class="font-semibold text-gray-900">{{ card.title }}</div>
            <div class="text-xs text-gray-500">{{ card.subtitle }}</div>
          </div>
        </div>

        <p class="text-sm text-gray-600 leading-relaxed">{{ card.description }}</p>

        <div
          v-if="card.available"
          class="mt-4 inline-flex items-center gap-1 text-sm font-medium transition"
          :class="props.modelValue === card.value ? 'text-brand' : 'text-gray-400 group-hover:text-brand'"
        >
          <span v-if="props.modelValue === card.value">Выбрано</span>
          <span v-else>Выбрать →</span>
        </div>
      </button>
    </div>
  </div>
</template>
