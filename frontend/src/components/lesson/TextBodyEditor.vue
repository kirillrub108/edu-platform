<script setup lang="ts">
import { Eye, Image as ImageIcon, Paperclip, Pencil } from 'lucide-vue-next'
import { useLessonKnowledgeStore } from '~/stores/lessonKnowledge'

/**
 * Markdown editor for a text lesson's body.
 *
 * Plain textarea + a small toolbar — no WYSIWYG dependency (project decision,
 * see docs/DECISIONS.md §58). Uploaded files become inline LessonMaterials and
 * are referenced as `material:{uuid}`; a signed URL is NEVER written into the
 * text, because it expires.
 *
 * Explicit save with a beforeunload guard. An upload that fails leaves the
 * already-typed text completely untouched — nothing is inserted and the error
 * surfaces above the toolbar.
 */
const props = defineProps<{ lessonId: string; modelValue: string }>()
const emit = defineEmits<{ 'update:modelValue': [string]; saved: [string] }>()

const { apiFetch } = useApi()
const store = useLessonKnowledgeStore()
const state = computed(() => store.getState(props.lessonId))
const { materials, onImageError } = useLessonMaterialMap(computed(() => props.lessonId))

const draft = ref(props.modelValue)
const savedText = ref(props.modelValue)
const textarea = ref<HTMLTextAreaElement | null>(null)
const imageInput = ref<HTMLInputElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)

const saving = ref(false)
const uploading = ref(false)
const error = ref('')
const showPreview = ref(false)

const dirty = computed(() => draft.value !== savedText.value)
const maxChars = computed(() => state.value.limits?.text_max_chars ?? 200000)
const tooLong = computed(() => draft.value.length > maxChars.value)

watch(
  () => props.modelValue,
  (next) => {
    // Only adopt an external value when the teacher has nothing unsaved.
    if (!dirty.value) {
      draft.value = next
      savedText.value = next
    }
  },
)

// ── Inserting at the caret ────────────────────────────────────────────────────

const insertAtCaret = (snippet: string) => {
  const el = textarea.value
  if (!el) {
    draft.value += snippet
    return
  }
  const start = el.selectionStart ?? draft.value.length
  const end = el.selectionEnd ?? start
  draft.value = draft.value.slice(0, start) + snippet + draft.value.slice(end)
  nextTick(() => {
    el.focus()
    const caret = start + snippet.length
    el.setSelectionRange(caret, caret)
  })
}

const uploadAndInsert = async (file: File, asImage: boolean) => {
  uploading.value = true
  error.value = ''
  try {
    const material = await store.uploadMaterial(props.lessonId, file, { isInline: true })
    const label = material.title || material.original_filename
    insertAtCaret(
      asImage ? `\n\n![${label}](material:${material.id})\n\n` : `\n\n[${label}](material:${material.id})\n\n`,
    )
  } catch {
    // The draft is deliberately untouched — the message from the store already
    // says which limit was hit (files, total size, inline count, extension).
    error.value = state.value.error ?? 'Не удалось загрузить файл'
  } finally {
    uploading.value = false
  }
}

const onPickImage = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file) await uploadAndInsert(file, true)
}

const onPickFile = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file) await uploadAndInsert(file, false)
}

const onDrop = async (event: DragEvent) => {
  const file = event.dataTransfer?.files?.[0]
  if (!file) return
  await uploadAndInsert(file, file.type.startsWith('image/'))
}

const onPaste = async (event: ClipboardEvent) => {
  const item = Array.from(event.clipboardData?.items ?? []).find((i) =>
    i.type.startsWith('image/'),
  )
  if (!item) return // plain text paste keeps the browser default
  const file = item.getAsFile()
  if (!file) return
  event.preventDefault()
  await uploadAndInsert(file, true)
}

// ── Saving ────────────────────────────────────────────────────────────────────

const save = async () => {
  if (saving.value || tooLong.value) return
  saving.value = true
  error.value = ''
  const submitted = draft.value
  try {
    const updated = await apiFetch<{ text_content: string | null }>(
      `/lessons/${props.lessonId}/text`,
      { method: 'PUT', body: { text_content: submitted } },
    )
    savedText.value = updated.text_content ?? ''
    emit('update:modelValue', savedText.value)
    emit('saved', savedText.value)
    // The save also sweeps inline materials the new text no longer references.
    await store.fetch(props.lessonId)
  } catch (e: any) {
    error.value = e?.data?.detail?.message ?? e?.data?.detail ?? 'Не удалось сохранить текст'
  } finally {
    saving.value = false
  }
}

const warnOnUnload = (event: BeforeUnloadEvent) => {
  if (!dirty.value) return
  event.preventDefault()
  event.returnValue = ''
}

onMounted(() => window.addEventListener('beforeunload', warnOnUnload))
onBeforeUnmount(() => window.removeEventListener('beforeunload', warnOnUnload))

// In-app navigation gets the same guard — beforeunload only covers the browser.
onBeforeRouteLeave(() => {
  if (!dirty.value) return true
  return window.confirm('Текст урока не сохранён. Уйти со страницы?')
})
</script>

<template>
  <section class="bg-white rounded-2xl border border-gray-100 p-6 shadow-soft space-y-4">
    <div class="flex items-center justify-between gap-3 flex-wrap">
      <h2 class="text-lg font-semibold text-gray-900">Текст урока</h2>
      <div class="flex items-center gap-2">
        <UiButton size="sm" variant="secondary" @click="showPreview = !showPreview">
          <template #icon>
            <component :is="showPreview ? Pencil : Eye" class="w-4 h-4" />
          </template>
          {{ showPreview ? 'Редактировать' : 'Предпросмотр' }}
        </UiButton>
        <UiButton size="sm" :loading="saving" :disabled="!dirty || tooLong" @click="save">
          Сохранить
        </UiButton>
      </div>
    </div>

    <p v-if="error" class="text-sm text-rose-600 bg-rose-50 rounded-xl px-4 py-2.5">
      {{ error }}
    </p>

    <div v-if="!showPreview" class="space-y-2">
      <div class="flex items-center gap-2 flex-wrap">
        <input ref="imageInput" type="file" accept="image/*" class="hidden" @change="onPickImage" />
        <input ref="fileInput" type="file" class="hidden" @change="onPickFile" />
        <UiButton
          size="sm"
          variant="secondary"
          :loading="uploading"
          @click="imageInput?.click()"
        >
          <template #icon><ImageIcon class="w-4 h-4" /></template>
          Изображение
        </UiButton>
        <UiButton
          size="sm"
          variant="secondary"
          :loading="uploading"
          @click="fileInput?.click()"
        >
          <template #icon><Paperclip class="w-4 h-4" /></template>
          Вложение
        </UiButton>
        <span class="text-xs text-gray-400">
          Перетащите файл в поле или вставьте картинку из буфера (Ctrl+V)
        </span>
      </div>

      <textarea
        ref="textarea"
        v-model="draft"
        rows="20"
        spellcheck="true"
        placeholder="# Заголовок&#10;&#10;Текст урока в Markdown. Поддерживаются заголовки, списки, цитаты, таблицы, код, ссылки и изображения."
        class="w-full rounded-xl border border-gray-200 px-4 py-3 font-mono text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-violet-200 focus:border-violet-300"
        :class="tooLong && 'border-rose-300 focus:ring-rose-200'"
        @drop.prevent="onDrop"
        @dragover.prevent
        @paste="onPaste"
      />

      <div class="flex items-center justify-between gap-3 text-xs">
        <span :class="tooLong ? 'text-rose-600 font-medium' : 'text-gray-400'">
          {{ draft.length.toLocaleString('ru-RU') }} /
          {{ maxChars.toLocaleString('ru-RU') }} символов
        </span>
        <span v-if="dirty" class="text-amber-600 font-medium">Есть несохранённые изменения</span>
        <span v-else class="text-gray-400">Сохранено</span>
      </div>
    </div>

    <div v-else class="rounded-xl border border-gray-100 p-5">
      <p v-if="!draft.trim()" class="text-sm text-gray-500">Пока пусто.</p>
      <KnowledgeMarkdownText
        v-else
        :content="draft"
        :materials="materials"
        :on-image-error="onImageError"
        class="text-base"
      />
    </div>
  </section>
</template>
