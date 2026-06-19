<script setup lang="ts">
const props = defineProps<{
  value: string
  tag?: string
  placeholder?: string
  saving?: boolean
  inputClass?: string
  displayClass?: string
}>()

const emit = defineEmits<{
  (e: 'save', value: string): void
  (e: 'cancel'): void
}>()

const editing = ref(false)
const draft = ref('')
const inputRef = ref<HTMLInputElement | null>(null)
let debounceTimer: ReturnType<typeof setTimeout> | null = null

const startEdit = () => {
  draft.value = props.value
  editing.value = true
  nextTick(() => inputRef.value?.select())
}

const commit = () => {
  if (debounceTimer) { clearTimeout(debounceTimer); debounceTimer = null }
  const trimmed = draft.value.trim()
  if (!trimmed) {
    // empty — restore original and cancel
    draft.value = props.value
    editing.value = false
    emit('cancel')
    return
  }
  editing.value = false
  if (trimmed !== props.value) {
    emit('save', trimmed)
  }
}

const cancel = () => {
  if (debounceTimer) { clearTimeout(debounceTimer); debounceTimer = null }
  draft.value = props.value
  editing.value = false
  emit('cancel')
}

const onInput = () => {
  if (debounceTimer) clearTimeout(debounceTimer)
  const trimmed = draft.value.trim()
  if (trimmed && trimmed !== props.value) {
    debounceTimer = setTimeout(commit, 800)
  }
}

const onKeydown = (e: KeyboardEvent) => {
  if (e.key === 'Enter' || e.key === 'Tab') {
    e.preventDefault()
    commit()
  } else if (e.key === 'Escape') {
    cancel()
  }
}

const onBlur = () => commit()
</script>

<template>
  <span class="inline-flex items-center gap-1.5 min-w-0">
    <input
      v-if="editing"
      ref="inputRef"
      v-model="draft"
      :class="['bg-transparent border-b border-current outline-none w-full min-w-24', inputClass]"
      @input="onInput"
      @keydown="onKeydown"
      @blur="onBlur"
    />
    <component
      :is="tag ?? 'span'"
      v-else
      :class="['cursor-pointer hover:opacity-70 transition-opacity truncate', displayClass]"
      :title="placeholder ?? value"
      @click="startEdit"
    >{{ value || placeholder }}</component>
    <span
      v-if="saving"
      class="shrink-0 w-3.5 h-3.5 rounded-full border-2 border-current border-t-transparent animate-spin opacity-50"
      aria-hidden="true"
    />
  </span>
</template>
