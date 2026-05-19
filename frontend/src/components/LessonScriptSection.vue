<script setup lang="ts">
defineProps<{
  modelValue: string
  saveStatus: 'idle' | 'saving' | 'saved' | 'error'
  scriptFile: File | null
  uploadingScript: boolean
  scriptUploadError: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'script-file-change': [file: File | null]
  'upload-script': []
}>()

const open = ref(true)
</script>

<template>
  <LessonScriptPanel
    :model-value="modelValue"
    :save-status="saveStatus"
    :open="open"
    :script-file="scriptFile"
    :uploading-script="uploadingScript"
    :script-upload-error="scriptUploadError"
    @update:model-value="emit('update:modelValue', $event)"
    @toggle="open = !open"
    @script-file-change="emit('script-file-change', $event)"
    @upload-script="emit('upload-script')"
  />
</template>
