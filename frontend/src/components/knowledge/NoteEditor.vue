<script setup lang="ts">
import type { KnowledgeNote } from '~/stores/lessonKnowledge'

const props = defineProps<{
  lessonId: string
  note: KnowledgeNote | null
  maxChars: number
}>()
const emit = defineEmits<{ saved: []; cancel: [] }>()

const store = useLessonKnowledgeStore()

const title = ref(props.note?.title ?? '')
const content = ref(props.note?.content ?? '')
const saving = ref(false)
const error = ref<string | null>(null)

const tooLong = computed(() => content.value.length > props.maxChars)
const canSave = computed(
  () => title.value.trim().length > 0 && content.value.trim().length > 0 && !tooLong.value,
)

const submit = async () => {
  if (!canSave.value) return
  saving.value = true
  error.value = null
  try {
    const payload = { title: title.value.trim(), content: content.value.trim() }
    if (props.note) await store.updateNote(props.lessonId, props.note.id, payload)
    else await store.createNote(props.lessonId, payload)
    emit('saved')
  } catch {
    error.value = store.getState(props.lessonId).error
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <form class="space-y-3" @submit.prevent="submit">
    <UiInput v-model="title" label="Заголовок конспекта" placeholder="Например: Ключевые формулы" />

    <div>
      <label class="block text-sm font-medium text-gray-700 mb-1">
        Текст (поддерживается Markdown)
      </label>
      <textarea
        v-model="content"
        rows="10"
        class="w-full rounded-xl border border-gray-200 px-3 py-2 text-sm font-mono leading-relaxed focus:outline-none focus:ring-2 focus:ring-violet-500/30"
        placeholder="# Заголовок&#10;&#10;- пункт списка&#10;- **важное**"
      />
      <div class="flex justify-between text-xs mt-1">
        <span class="text-gray-400">
          Поддерживаются заголовки, списки, **жирный**, *курсив*, `код`, ссылки.
        </span>
        <span :class="tooLong ? 'text-rose-600 font-medium' : 'text-gray-400'">
          {{ content.length }} / {{ maxChars }}
        </span>
      </div>
    </div>

    <p v-if="error" class="text-sm text-rose-600">{{ error }}</p>

    <div class="flex gap-2">
      <UiButton type="submit" size="sm" :loading="saving" :disabled="!canSave">
        {{ note ? 'Сохранить' : 'Добавить конспект' }}
      </UiButton>
      <UiButton type="button" variant="ghost" size="sm" @click="emit('cancel')">Отмена</UiButton>
    </div>
  </form>
</template>
