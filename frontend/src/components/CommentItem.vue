<script setup lang="ts">
import { Pencil, Trash2, X, Check } from 'lucide-vue-next'
import type { Comment } from '~/stores/comments'
import { relativeTime } from '~/utils/relativeTime'

const props = defineProps<{
  comment: Comment
  canEdit: boolean
  canDelete: boolean
}>()

const emit = defineEmits<{
  (e: 'update', content: string): void
  (e: 'delete'): void
}>()

const isEditing = ref(false)
const draft = ref('')
const saving = ref(false)

const initials = computed(() => {
  const src = props.comment.author.full_name || '?'
  const parts = src.trim().split(/\s+/).slice(0, 2)
  return parts.map((p) => p[0]?.toUpperCase() ?? '').join('') || '?'
})

const isTeacher = computed(() => props.comment.author.role === 'teacher')

const beginEdit = () => {
  draft.value = props.comment.content
  isEditing.value = true
}

const cancelEdit = () => {
  isEditing.value = false
  draft.value = ''
}

const submitEdit = async () => {
  const trimmed = draft.value.trim()
  if (!trimmed || trimmed === props.comment.content || saving.value) return
  saving.value = true
  try {
    emit('update', trimmed)
    isEditing.value = false
  } finally {
    saving.value = false
  }
}

const confirmDelete = () => {
  if (typeof window !== 'undefined' && !window.confirm('Удалить комментарий?')) return
  emit('delete')
}
</script>

<template>
  <div class="flex gap-2.5">
    <div
      class="w-8 h-8 rounded-full grid place-items-center text-xs font-semibold flex-shrink-0"
      :class="isTeacher ? 'bg-violet-100 text-violet-700' : 'bg-gray-100 text-gray-600'"
    >
      {{ initials }}
    </div>
    <div class="flex-1 min-w-0">
      <div class="flex items-center gap-2 flex-wrap text-xs mb-0.5">
        <span class="font-medium text-gray-900 truncate">
          {{ comment.author.full_name || 'Без имени' }}
        </span>
        <span
          v-if="isTeacher"
          class="px-1.5 py-0.5 rounded-md bg-violet-50 text-violet-700 text-[10px] font-medium"
        >
          Преподаватель
        </span>
        <span class="text-gray-400">{{ relativeTime(comment.created_at) }}</span>
        <span v-if="comment.is_edited" class="text-gray-400">· изменено</span>
      </div>

      <div v-if="!isEditing" class="text-sm text-gray-800 whitespace-pre-wrap break-words">
        {{ comment.content }}
      </div>

      <div v-else class="mt-1">
        <textarea
          v-model="draft"
          rows="3"
          maxlength="2000"
          class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm
                 focus:outline-none focus:border-violet-400 resize-none"
        />
        <div class="flex items-center gap-2 mt-1.5">
          <button
            type="button"
            class="px-2.5 py-1 rounded-md text-xs font-medium bg-violet-600 text-white
                   hover:bg-violet-500 transition disabled:opacity-50 inline-flex items-center gap-1"
            :disabled="saving || !draft.trim()"
            @click="submitEdit"
          >
            <Check class="w-3 h-3" />
            Сохранить
          </button>
          <button
            type="button"
            class="px-2.5 py-1 rounded-md text-xs text-gray-600 hover:bg-gray-100
                   transition inline-flex items-center gap-1"
            @click="cancelEdit"
          >
            <X class="w-3 h-3" />
            Отмена
          </button>
        </div>
      </div>

      <div v-if="!isEditing && (canEdit || canDelete)" class="flex items-center gap-3 mt-1">
        <button
          v-if="canEdit"
          type="button"
          class="text-xs text-gray-400 hover:text-violet-600 transition inline-flex items-center gap-1"
          @click="beginEdit"
        >
          <Pencil class="w-3 h-3" />
          Изменить
        </button>
        <button
          v-if="canDelete"
          type="button"
          class="text-xs text-gray-400 hover:text-rose-600 transition inline-flex items-center gap-1"
          @click="confirmDelete"
        >
          <Trash2 class="w-3 h-3" />
          Удалить
        </button>
      </div>
    </div>
  </div>
</template>
