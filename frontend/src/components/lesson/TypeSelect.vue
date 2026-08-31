<script setup lang="ts">
import { Check, ChevronDown, FileText, Video } from 'lucide-vue-next'

const props = defineProps<{ modelValue: 'video' | 'text' }>()
const emit = defineEmits<{ 'update:modelValue': ['video' | 'text'] }>()

const options = [
  { value: 'video' as const, label: 'Видео', icon: Video },
  { value: 'text' as const, label: 'Текст', icon: FileText },
]

const open = ref(false)
const root = ref<HTMLElement | null>(null)

const current = computed(() => options.find((o) => o.value === props.modelValue) ?? options[0])

const select = (value: 'video' | 'text') => {
  emit('update:modelValue', value)
  open.value = false
}

const onDocumentClick = (event: MouseEvent) => {
  if (root.value && !root.value.contains(event.target as Node)) open.value = false
}

onMounted(() => document.addEventListener('click', onDocumentClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocumentClick))
</script>

<template>
  <div ref="root" class="relative">
    <button
      type="button"
      aria-label="Тип урока"
      title="Тип урока — по умолчанию видео"
      class="flex items-center gap-1.5 border border-gray-200 rounded-lg pl-3 pr-2 py-1.5 text-sm bg-white hover:border-gray-300 focus:outline-none focus:ring-2 focus:ring-brand/30"
      @click="open = !open"
    >
      <component :is="current.icon" class="w-3.5 h-3.5 text-gray-500" />
      {{ current.label }}
      <ChevronDown class="w-3.5 h-3.5 text-gray-400 transition" :class="open && 'rotate-180'" />
    </button>

    <ul
      v-if="open"
      class="absolute z-10 mt-1 w-32 rounded-lg border border-gray-100 bg-white py-1 shadow-lg"
    >
      <li v-for="option in options" :key="option.value">
        <button
          type="button"
          class="flex w-full items-center gap-2 px-3 py-1.5 text-sm hover:bg-brand/5"
          :class="option.value === modelValue ? 'text-brand font-medium' : 'text-gray-700'"
          @click="select(option.value)"
        >
          <component :is="option.icon" class="w-3.5 h-3.5 shrink-0" />
          <span class="flex-1 text-left">{{ option.label }}</span>
          <Check v-if="option.value === modelValue" class="w-3.5 h-3.5 shrink-0" />
        </button>
      </li>
    </ul>
  </div>
</template>
