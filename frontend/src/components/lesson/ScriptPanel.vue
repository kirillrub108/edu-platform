<script setup lang="ts">
import { ChevronDown, FileText } from 'lucide-vue-next'

const props = defineProps<{
  modelValue: string
  saveStatus: 'idle' | 'saving' | 'saved' | 'error'
  open: boolean
  scriptFile: File | null
  uploadingScript: boolean
  scriptUploadError: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  toggle: []
  'script-file-change': [file: File | null]
  'upload-script': []
}>()

const wordCount = computed(() =>
  props.modelValue.split(/\s+/).filter(Boolean).length,
)

const onScriptFileChange = (e: Event) => {
  const input = e.target as HTMLInputElement
  emit('script-file-change', input.files?.[0] ?? null)
}
</script>

<template>
  <section class="bg-white rounded-2xl border border-gray-100 shadow-soft overflow-hidden">
    <button
      type="button"
      class="w-full flex items-center justify-between px-6 py-4 hover:bg-gray-50 transition"
      @click="emit('toggle')"
    >
      <div class="text-left">
        <h2 class="text-lg font-semibold text-gray-900">Текст доклада</h2>
        <p class="text-sm text-gray-500">Введите полный текст или загрузите файл. LLM разобьёт его по слайдам.</p>
      </div>
      <ChevronDown
        class="w-5 h-5 text-gray-400 transition-transform duration-200 shrink-0"
        :class="{ 'rotate-180': open }"
      />
    </button>
    <div v-if="open" class="px-6 pb-6">
      <div class="flex flex-wrap gap-2 items-center mb-3">
        <label class="cursor-pointer inline-flex items-center gap-2 px-3 py-1.5 border border-gray-200 rounded-lg text-sm text-gray-700 hover:bg-violet-50 hover:border-violet-200 hover:text-violet-700 transition">
          <FileText class="w-4 h-4" />
          {{ scriptFile ? scriptFile.name : 'Загрузить из файла' }}
          <input
            type="file"
            accept=".txt,.md,.markdown,.pdf,.docx,.doc,.rtf,.odt,.html,.htm"
            class="hidden"
            @change="onScriptFileChange"
          />
        </label>
        <UiButton
          v-if="scriptFile"
          variant="primary"
          size="sm"
          :loading="uploadingScript"
          @click="emit('upload-script')"
        >
          Извлечь текст
        </UiButton>
        <span class="text-xs text-gray-500">TXT, MD, PDF, DOCX, DOC, RTF, ODT, HTML</span>
      </div>
      <p v-if="scriptUploadError" class="mb-2 text-sm text-rose-600">{{ scriptUploadError }}</p>

      <textarea
        :value="modelValue"
        rows="8"
        placeholder="Введите текст доклада…"
        class="w-full bg-white px-4 py-3 text-sm leading-relaxed border border-gray-200 rounded-xl resize-y focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400 transition"
        @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
      />
      <div class="flex justify-between items-center mt-2">
        <span class="text-xs text-gray-500">{{ wordCount }} слов</span>
        <span
          v-if="saveStatus === 'saving'"
          class="text-xs text-gray-500"
        >Сохранение…</span>
        <span
          v-else-if="saveStatus === 'saved'"
          class="text-xs text-emerald-600"
        >Сохранено</span>
        <span
          v-else-if="saveStatus === 'error'"
          class="text-xs text-rose-600"
        >Ошибка сохранения</span>
      </div>
    </div>
  </section>
</template>
