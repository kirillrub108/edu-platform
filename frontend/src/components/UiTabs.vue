<script setup lang="ts">
interface Tab {
  id: string
  label: string
}

const props = defineProps<{ tabs: Tab[]; modelValue: string }>()
const emit = defineEmits<{ 'update:modelValue': [id: string] }>()

const tabRefs = ref<HTMLButtonElement[]>([])

const onKeydown = (e: KeyboardEvent, idx: number) => {
  const count = props.tabs.length
  let next = -1
  if (e.key === 'ArrowRight') next = (idx + 1) % count
  else if (e.key === 'ArrowLeft') next = (idx - 1 + count) % count
  else if (e.key === 'Home') next = 0
  else if (e.key === 'End') next = count - 1
  if (next !== -1) {
    e.preventDefault()
    emit('update:modelValue', props.tabs[next].id)
    nextTick(() => tabRefs.value[next]?.focus())
  }
}
</script>

<template>
  <div
    role="tablist"
    class="flex gap-1 border-b border-gray-200 mb-6"
  >
    <button
      v-for="(tab, idx) in tabs"
      :key="tab.id"
      :ref="(el) => { if (el) tabRefs[idx] = el as HTMLButtonElement }"
      role="tab"
      :aria-selected="modelValue === tab.id"
      :aria-controls="`tabpanel-${tab.id}`"
      :id="`tab-${tab.id}`"
      :tabindex="modelValue === tab.id ? 0 : -1"
      :class="[
        'px-5 py-2.5 text-sm font-medium rounded-t-lg transition-colors outline-none',
        'focus-visible:ring-2 focus-visible:ring-violet-500/40 focus-visible:ring-offset-1',
        modelValue === tab.id
          ? 'text-violet-700 border-b-2 border-violet-600 -mb-px bg-white'
          : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50',
      ]"
      @click="emit('update:modelValue', tab.id)"
      @keydown="onKeydown($event, idx)"
    >
      {{ tab.label }}
    </button>
  </div>
</template>
