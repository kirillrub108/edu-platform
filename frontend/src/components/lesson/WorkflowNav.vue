<script setup lang="ts">
// Step navigator for the teacher lesson "Урок" wizard. Pure presentation —
// the page owns the step list and the active key. Rendered twice (vertical in
// the sticky right column, horizontal as mobile chips) off the same state.
interface Step {
  key: string
  title: string
  status: { text: string; tone: string } | null
}

defineProps<{
  steps: Step[]
  modelValue: string
  orientation?: 'vertical' | 'horizontal'
}>()

const emit = defineEmits<{ 'update:modelValue': [key: string] }>()
</script>

<template>
  <nav
    aria-label="Этапы создания урока"
    :class="orientation === 'horizontal'
      ? 'flex gap-2 overflow-x-auto pb-1 -mx-1 px-1'
      : 'flex flex-col gap-1'"
  >
    <button
      v-for="(step, idx) in steps"
      :key="step.key"
      type="button"
      :aria-current="modelValue === step.key ? 'step' : undefined"
      :class="[
        'flex items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition shrink-0 outline-none',
        'focus-visible:ring-2 focus-visible:ring-violet-500/40',
        modelValue === step.key
          ? 'border-violet-300 bg-violet-50'
          : 'border-transparent hover:bg-gray-50',
      ]"
      @click="emit('update:modelValue', step.key)"
    >
      <span
        :class="[
          'grid place-items-center w-6 h-6 rounded-full text-xs font-semibold shrink-0',
          modelValue === step.key ? 'bg-violet-600 text-white' : 'bg-gray-100 text-gray-500',
        ]"
      >{{ idx + 1 }}</span>
      <span class="min-w-0">
        <span class="block text-sm font-medium text-gray-900 whitespace-nowrap">{{ step.title }}</span>
        <span
          v-if="step.status"
          :class="['mt-0.5 inline-flex items-center px-1.5 py-0.5 rounded-full text-[11px] font-medium leading-none', step.status.tone]"
        >{{ step.status.text }}</span>
      </span>
    </button>
  </nav>
</template>
