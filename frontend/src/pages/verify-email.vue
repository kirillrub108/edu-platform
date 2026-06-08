<script setup lang="ts">
import { CheckCircle2, XCircle, Loader2 } from 'lucide-vue-next'

definePageMeta({ layout: 'bare' })

const route = useRoute()
const auth = useAuthStore()
const { apiFetch } = useApi()

type State = 'verifying' | 'success' | 'error'
const state = ref<State>('verifying')
const errorText = ref('')
const resending = ref(false)
const resendMessage = ref('')

const REASONS: Record<string, string> = {
  expired: 'Ссылка устарела. Запросите новое письмо.',
  used: 'Эта ссылка уже была использована.',
  invalid: 'Ссылка недействительна. Запросите новое письмо.',
}

const dashboardLink = computed(() =>
  auth.user?.role === 'student' ? '/student/dashboard' : '/dashboard',
)

const verify = async () => {
  const raw = route.query.token
  const token = Array.isArray(raw) ? raw[0] : raw
  if (!token) {
    state.value = 'error'
    errorText.value = REASONS.invalid
    return
  }
  try {
    await apiFetch('/auth/verify-email', { method: 'POST', body: { token } })
    // Refresh user so the badge clears and AI unlocks without a re-login.
    await auth.fetchMe()
    state.value = 'success'
  } catch (e: any) {
    state.value = 'error'
    const reason = e?.data?.detail as string | undefined
    errorText.value = (reason && REASONS[reason]) || 'Не удалось подтвердить email.'
  }
}

// Resend is only possible while authenticated (the endpoint requires auth).
const resend = async () => {
  if (resending.value) return
  resending.value = true
  resendMessage.value = ''
  try {
    await apiFetch('/auth/resend-verification', { method: 'POST' })
    resendMessage.value = 'Новое письмо отправлено. Проверьте почту.'
  } catch (e: any) {
    resendMessage.value =
      e?.data?.detail ?? 'Не удалось отправить письмо. Войдите в аккаунт и попробуйте снова.'
  } finally {
    resending.value = false
  }
}

onMounted(verify)
</script>

<template>
  <div class="min-h-screen grid place-items-center bg-violet-50/30 px-4">
    <div class="bg-white rounded-2xl border border-gray-100 shadow-soft p-8 w-full max-w-md text-center space-y-4">
      <template v-if="state === 'verifying'">
        <Loader2 class="w-10 h-10 text-violet-500 mx-auto animate-spin" />
        <h1 class="text-lg font-semibold text-gray-900">Подтверждаем email…</h1>
      </template>

      <template v-else-if="state === 'success'">
        <CheckCircle2 class="w-12 h-12 text-emerald-500 mx-auto" />
        <h1 class="text-lg font-semibold text-gray-900">Email подтверждён</h1>
        <p class="text-sm text-gray-500">Теперь доступны все AI-функции.</p>
        <NuxtLink
          :to="auth.isAuthenticated ? dashboardLink : '/login'"
          class="inline-block px-5 py-2.5 rounded-xl text-sm font-medium bg-violet-700 hover:bg-violet-600 text-white shadow-sm transition"
        >
          {{ auth.isAuthenticated ? 'В личный кабинет' : 'Войти' }}
        </NuxtLink>
      </template>

      <template v-else>
        <XCircle class="w-12 h-12 text-rose-500 mx-auto" />
        <h1 class="text-lg font-semibold text-gray-900">Не удалось подтвердить</h1>
        <p class="text-sm text-gray-500">{{ errorText }}</p>

        <div v-if="resendMessage" class="text-sm text-violet-700">{{ resendMessage }}</div>

        <div class="flex flex-col gap-2 pt-1">
          <button
            v-if="auth.isAuthenticated"
            type="button"
            :disabled="resending"
            class="px-5 py-2.5 rounded-xl text-sm font-medium bg-violet-700 hover:bg-violet-600 text-white shadow-sm transition disabled:opacity-50"
            @click="resend"
          >
            {{ resending ? 'Отправка…' : 'Отправить письмо повторно' }}
          </button>
          <NuxtLink
            to="/login"
            class="text-sm font-medium text-gray-600 hover:text-violet-700 transition"
          >
            На страницу входа
          </NuxtLink>
        </div>
      </template>
    </div>
  </div>
</template>
