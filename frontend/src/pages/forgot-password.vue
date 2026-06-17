<script setup lang="ts">
import { AlertCircle, MailCheck } from 'lucide-vue-next'

const auth = useAuthStore()
const email = ref('')
const error = ref<string | null>(null)
const loading = ref(false)
const sent = ref(false)
const sentEmail = ref('')

const submit = async () => {
  error.value = null
  loading.value = true
  try {
    await auth.forgotPassword(email.value)
    // The server never reveals whether the account exists — always show the
    // same confirmation, echoing back the address the user typed.
    sentEmail.value = email.value
    sent.value = true
  } catch (e: any) {
    error.value = e?.data?.detail ?? 'Не удалось отправить письмо. Попробуйте позже.'
  } finally {
    loading.value = false
  }
}

onMounted(restoreScroll)
</script>

<template>
  <div class="px-6 py-12 sm:py-16 flex justify-center">
    <div class="w-full max-w-sm">
      <div class="mb-6 text-center">
        <div class="mb-3 flex justify-center">
          <AppLogo :with-text="false" size="lg" />
        </div>
        <h1 class="text-xl font-semibold text-gray-900">Восстановление пароля</h1>
        <p class="mt-1 text-sm text-gray-500">
          Укажите email — пришлём ссылку для сброса пароля
        </p>
      </div>

      <div class="rounded-2xl border border-gray-100 bg-white p-8 shadow-soft">
        <div
          v-if="sent"
          class="flex flex-col items-center gap-3 text-center"
        >
          <MailCheck class="h-10 w-10 text-emerald-500" />
          <p class="text-sm text-gray-600">
            Если аккаунт
            <span class="font-medium text-gray-900">{{ sentEmail }}</span>
            существует, мы отправили на него ссылку для сброса пароля. Проверьте почту.
          </p>
        </div>

        <form v-else class="space-y-4" @submit.prevent="submit">
          <UiInput
            v-model="email"
            label="Email"
            type="email"
            placeholder="you@example.com"
            autocomplete="email"
          />

          <p
            v-if="error"
            class="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700"
          >
            <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
            <span>{{ error }}</span>
          </p>

          <UiButton type="submit" variant="primary" size="lg" block :loading="loading">
            {{ loading ? 'Отправка…' : 'Отправить ссылку' }}
          </UiButton>
        </form>
      </div>

      <p class="mt-5 text-center text-sm text-gray-500">
        Вспомнили пароль?
        <NuxtLink to="/login" class="font-medium text-violet-700 hover:underline">Войти</NuxtLink>
      </p>
    </div>
  </div>
</template>
