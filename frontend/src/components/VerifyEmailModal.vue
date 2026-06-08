<script setup lang="ts">
import { MailWarning, CheckCircle2 } from 'lucide-vue-next'

const auth = useAuthStore()
const { verifyPromptOpen, user } = storeToRefs(auth)
const { apiFetch } = useApi()

type State = 'idle' | 'sending' | 'sent' | 'cooldown' | 'error'
const state = ref<State>('idle')
const message = ref('')

const close = () => {
  auth.closeVerifyPrompt()
  // Reset for next open.
  state.value = 'idle'
  message.value = ''
}

const resend = async () => {
  if (state.value === 'sending') return
  state.value = 'sending'
  message.value = ''
  try {
    await apiFetch('/auth/resend-verification', { method: 'POST' })
    state.value = 'sent'
  } catch (e: any) {
    const status = e?.response?.status
    if (status === 429) {
      state.value = 'cooldown'
      message.value = e?.data?.detail ?? 'Письмо уже отправлено. Подождите немного.'
    } else if (status === 400) {
      // Already verified server-side — sync local state and close.
      await auth.fetchMe()
      close()
    } else {
      state.value = 'error'
      message.value = e?.data?.detail ?? 'Не удалось отправить письмо. Попробуйте позже.'
    }
  }
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="verifyPromptOpen"
      class="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4"
      @click.self="close"
    >
      <div class="bg-white rounded-2xl shadow-xl p-6 w-full max-w-md space-y-4">
        <div class="flex items-start gap-3">
          <div class="w-10 h-10 rounded-xl bg-amber-100 text-amber-600 grid place-items-center shrink-0">
            <MailWarning class="w-5 h-5" />
          </div>
          <div>
            <h3 class="text-base font-semibold text-gray-900">Подтвердите email</h3>
            <p class="text-sm text-gray-500 mt-1">
              AI-функции доступны только после подтверждения почты.
              <template v-if="user?.email">
                Мы отправили ссылку на <span class="font-medium text-gray-700">{{ user.email }}</span>.
              </template>
              Не пришло письмо — отправьте повторно.
            </p>
          </div>
        </div>

        <div
          v-if="state === 'sent'"
          class="flex items-center gap-2 text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-xl px-3 py-2"
        >
          <CheckCircle2 class="w-4 h-4 shrink-0" />
          Письмо отправлено. Проверьте почту.
        </div>
        <div
          v-else-if="state === 'cooldown'"
          class="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-xl px-3 py-2"
        >
          {{ message }}
        </div>
        <div
          v-else-if="state === 'error'"
          class="text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-xl px-3 py-2"
        >
          {{ message }}
        </div>

        <div class="flex justify-end gap-2 pt-1">
          <button
            type="button"
            class="text-sm px-4 py-2 rounded-lg border border-gray-200 text-gray-700 hover:bg-gray-50 transition"
            @click="close"
          >
            Закрыть
          </button>
          <button
            type="button"
            :disabled="state === 'sending'"
            class="text-sm px-4 py-2 rounded-lg bg-violet-600 text-white hover:bg-violet-700 transition disabled:opacity-50"
            @click="resend"
          >
            {{ state === 'sending' ? 'Отправка…' : 'Отправить письмо повторно' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
