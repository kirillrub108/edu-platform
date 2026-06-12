<script setup lang="ts">
import { Send } from 'lucide-vue-next'
import type { ThreadMessage } from '~/stores/assignments'
import { formatAssignmentDateTime } from '~/utils/assignments'

const props = defineProps<{
  messages: ThreadMessage[]
  posting?: boolean
  disabled?: boolean
}>()
const emit = defineEmits<{ send: [body: string] }>()

const draft = ref('')

const canSend = computed(() => draft.value.trim().length > 0 && !props.posting && !props.disabled)

const send = () => {
  if (!canSend.value) return
  emit('send', draft.value.trim())
  draft.value = ''
}
</script>

<template>
  <div class="space-y-3">
    <h4 class="text-sm font-semibold text-gray-700">Переписка</h4>

    <div v-if="messages.length === 0" class="text-xs text-gray-400">
      Сообщений пока нет.
    </div>

    <ul v-else class="space-y-2 max-h-64 overflow-y-auto pr-1">
      <li
        v-for="m in messages"
        :key="m.id"
        class="rounded-xl px-3 py-2"
        :class="m.author.role === 'teacher' ? 'bg-violet-50' : 'bg-gray-50'"
      >
        <div class="flex items-center gap-2 text-xs text-gray-500 mb-0.5">
          <span class="font-medium text-gray-700">{{ m.author.full_name ?? 'Пользователь' }}</span>
          <span
            class="px-1.5 py-0.5 rounded-full"
            :class="m.author.role === 'teacher'
              ? 'bg-violet-100 text-violet-700'
              : 'bg-gray-100 text-gray-600'"
          >{{ m.author.role === 'teacher' ? 'преподаватель' : 'студент' }}</span>
          <span class="ml-auto tabular-nums">{{ formatAssignmentDateTime(m.created_at) }}</span>
        </div>
        <p class="text-sm text-gray-800 whitespace-pre-wrap break-words">{{ m.body }}</p>
      </li>
    </ul>

    <div v-if="!disabled" class="flex items-end gap-2">
      <textarea
        v-model="draft"
        rows="2"
        placeholder="Написать сообщение…"
        class="flex-1 resize-none border border-gray-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400"
        @keydown.enter.exact.prevent="send"
      />
      <UiButton size="sm" :loading="posting" :disabled="!canSend" @click="send">
        <template #icon><Send class="w-3.5 h-3.5" /></template>
        Отправить
      </UiButton>
    </div>
  </div>
</template>
