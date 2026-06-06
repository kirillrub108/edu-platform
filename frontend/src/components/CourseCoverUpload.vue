<script setup lang="ts">
import { ImageIcon, Loader2, Trash2, RefreshCw } from 'lucide-vue-next'

defineProps<{
  modelValue: string | null
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string | null): void
}>()

const { apiFetch } = useApi()
const uploading = ref(false)
const error = ref<string | null>(null)
const isDragOver = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)

const MAX_SIZE = 5 * 1024 * 1024
const ALLOWED_TYPES = ['image/jpeg', 'image/png', 'image/webp']

function openFilePicker() {
  fileInputRef.value?.click()
}

function onDragEnter(e: DragEvent) {
  e.preventDefault()
  isDragOver.value = true
}

function onDragLeave(e: DragEvent) {
  e.preventDefault()
  isDragOver.value = false
}

function onDragOver(e: DragEvent) {
  e.preventDefault()
}

async function onDrop(e: DragEvent) {
  e.preventDefault()
  isDragOver.value = false
  const file = e.dataTransfer?.files[0]
  if (file) await handleFile(file)
}

async function onFileChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (file) await handleFile(file)
  if (fileInputRef.value) fileInputRef.value.value = ''
}

async function handleFile(file: File) {
  error.value = null
  if (!ALLOWED_TYPES.includes(file.type)) {
    error.value = 'Допустимые форматы: JPEG, PNG, WebP'
    return
  }
  if (file.size > MAX_SIZE) {
    error.value = 'Файл слишком большой (максимум 5 МБ)'
    return
  }
  uploading.value = true
  try {
    const formData = new FormData()
    formData.append('file', file)
    const result = await apiFetch<{ file_url: string }>('/uploads/cover', {
      method: 'POST',
      body: formData,
    })
    emit('update:modelValue', result.file_url)
  } catch (e: any) {
    error.value = e?.data?.detail ?? 'Ошибка при загрузке файла'
  } finally {
    uploading.value = false
  }
}

function removeCover() {
  emit('update:modelValue', null)
  error.value = null
}
</script>

<template>
  <div>
    <p class="text-sm font-medium text-gray-700 mb-3">Обложка курса</p>

    <!-- Preview state -->
    <div v-if="modelValue && !uploading" class="group relative rounded-2xl overflow-hidden border border-gray-200 shadow-sm h-52">
      <img :src="modelValue" alt="Обложка" class="w-full h-full object-cover" />
      <!-- hover overlay -->
      <div class="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity duration-200 flex flex-col items-center justify-center gap-3">
        <button
          type="button"
          class="inline-flex items-center gap-1.5 text-sm font-medium text-white bg-white/20 hover:bg-white/30 border border-white/40 rounded-xl px-4 py-2 transition-colors"
          @click="openFilePicker"
        >
          <RefreshCw class="w-4 h-4" />
          Сменить
        </button>
        <button
          type="button"
          class="inline-flex items-center gap-1.5 text-sm font-medium text-rose-200 hover:text-rose-100 hover:bg-white/10 rounded-xl px-4 py-2 transition-colors"
          @click="removeCover"
        >
          <Trash2 class="w-4 h-4" />
          Удалить
        </button>
      </div>
    </div>

    <!-- Uploading state -->
    <div
      v-else-if="uploading"
      class="rounded-2xl h-52 flex flex-col items-center justify-center bg-violet-50 border-2 border-dashed border-violet-300"
    >
      <Loader2 class="w-9 h-9 animate-spin text-violet-400 mb-3" />
      <p class="text-sm font-medium text-violet-600">Загружаем обложку…</p>
    </div>

    <!-- Empty state -->
    <div
      v-else
      :class="[
        'relative rounded-2xl h-52 flex flex-col items-center justify-center cursor-pointer',
        'border-2 border-dashed transition-all duration-200 overflow-hidden',
        isDragOver
          ? 'border-violet-500 bg-violet-50 scale-[1.01]'
          : 'border-violet-200 hover:border-violet-400 bg-gradient-to-br from-violet-50/60 to-fuchsia-50/40 hover:from-violet-50 hover:to-fuchsia-50',
      ]"
      @click="openFilePicker"
      @dragenter="onDragEnter"
      @dragleave="onDragLeave"
      @dragover="onDragOver"
      @drop="onDrop"
    >
      <!-- pointer-events-none prevents child elements from triggering dragleave on the container -->
      <div class="pointer-events-none flex flex-col items-center px-6 text-center">
        <div class="w-14 h-14 rounded-2xl bg-violet-100 flex items-center justify-center mb-4">
          <ImageIcon class="w-7 h-7 text-violet-500" />
        </div>
        <p class="text-sm font-semibold text-violet-700 mb-1">Перетащите изображение</p>
        <p class="text-xs text-gray-400 mb-3">или нажмите для выбора файла</p>
        <span class="inline-flex items-center rounded-full bg-violet-100 px-3 py-1 text-xs font-medium text-violet-600">
          JPEG · PNG · WebP · до 5 МБ
        </span>
      </div>
    </div>

    <p
      v-if="error"
      class="text-sm text-red-600 bg-red-50 border border-red-200 rounded-xl px-3 py-2 mt-3"
    >
      {{ error }}
    </p>

    <input
      ref="fileInputRef"
      type="file"
      accept="image/jpeg,image/png,image/webp"
      class="hidden"
      @change="onFileChange"
    />
  </div>
</template>
