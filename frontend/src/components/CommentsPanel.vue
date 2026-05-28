<script setup lang="ts">
import { MessageSquare, Send } from 'lucide-vue-next'
import type { Comment } from '~/stores/comments'

const props = defineProps<{
  lessonId: string
  canDelete: (c: Comment) => boolean
  canEdit?: (c: Comment) => boolean
}>()

const commentsStore = useCommentsStore()
const auth = useAuthStore()

const state = computed(() => commentsStore.getState(props.lessonId))

const draft = ref('')
const sending = ref(false)

const remaining = computed(() => 2000 - draft.value.length)
const canSubmit = computed(
  () => !sending.value && draft.value.trim().length > 0 && remaining.value >= 0,
)

const submit = async () => {
  if (!canSubmit.value) return
  sending.value = true
  try {
    await commentsStore.create(props.lessonId, draft.value.trim())
    draft.value = ''
  } catch {
    // store sets state.error; nothing else to do here
  } finally {
    sending.value = false
  }
}

const onUpdate = async (commentId: string, content: string) => {
  try {
    await commentsStore.update(props.lessonId, commentId, content)
  } catch {
    /* error already in state */
  }
}

const onDelete = async (commentId: string) => {
  try {
    await commentsStore.remove(props.lessonId, commentId)
  } catch {
    /* error already in state */
  }
}

const defaultCanEdit = (c: Comment): boolean =>
  !!auth.user && c.author.id === auth.user.id

const resolveCanEdit = (c: Comment): boolean =>
  props.canEdit ? props.canEdit(c) : defaultCanEdit(c)

watch(
  () => props.lessonId,
  async (id) => {
    if (!id) return
    await commentsStore.fetch(id)
    commentsStore.startPolling(id)
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  commentsStore.stopPolling()
})
</script>

<template>
  <section
    class="bg-white border border-gray-100 rounded-2xl flex flex-col overflow-hidden"
  >
    <header class="px-4 py-3 border-b border-gray-100 flex items-center gap-2">
      <MessageSquare class="w-4 h-4 text-violet-600" />
      <h3 class="text-sm font-semibold text-gray-900">
        Комментарии
        <span class="text-gray-400 font-normal">({{ state.total }})</span>
      </h3>
    </header>

    <form class="p-4 border-b border-gray-100 space-y-2" @submit.prevent="submit">
      <textarea
        v-model="draft"
        rows="3"
        maxlength="2000"
        placeholder="Напишите комментарий…"
        class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm
               focus:outline-none focus:border-violet-400 resize-none"
      />
      <div class="flex items-center justify-between">
        <span
          class="text-xs"
          :class="remaining < 0 ? 'text-rose-500' : 'text-gray-400'"
        >
          {{ draft.length }} / 2000
        </span>
        <UiButton
          size="sm"
          type="submit"
          :disabled="!canSubmit"
          :loading="sending"
        >
          <template #icon>
            <Send class="w-3.5 h-3.5" />
          </template>
          Отправить
        </UiButton>
      </div>
      <p v-if="state.error" class="text-xs text-rose-600">{{ state.error }}</p>
    </form>

    <div class="flex-1 overflow-y-auto p-4 space-y-4">
      <p v-if="state.loading && !state.items.length" class="text-sm text-gray-400">
        Загрузка…
      </p>
      <p v-else-if="!state.items.length" class="text-sm text-gray-400 text-center py-6">
        Будьте первым, кто оставит комментарий
      </p>
      <CommentItem
        v-for="c in state.items"
        :key="c.id"
        :comment="c"
        :can-edit="resolveCanEdit(c)"
        :can-delete="canDelete(c)"
        @update="(content) => onUpdate(c.id, content)"
        @delete="() => onDelete(c.id)"
      />
    </div>
  </section>
</template>
