<script setup lang="ts">
import { AlertCircle } from 'lucide-vue-next'

const route = useRoute()
const auth = useAuthStore()

const token = computed(() => {
  const raw = route.query.token
  return Array.isArray(raw) ? raw[0] : raw
})

// Two ways in: the link from the deletion email, or the original credentials
// for someone who no longer has the mail. Same endpoint, same opaque failure.
const email = ref('')
const password = ref('')
const error = ref<string | null>(null)
const loading = ref(false)

const FAILED =
  'Не удалось восстановить аккаунт. Ссылка устарела, срок восстановления истёк или данные неверны.'

const finish = async () => {
  await auth.fetchMe()
  await navigateTo(auth.user?.role === 'student' ? '/student/dashboard' : '/dashboard')
}

const submitToken = async () => {
  if (!token.value) return
  error.value = null
  loading.value = true
  try {
    await auth.restoreAccount({ token: token.value })
    await finish()
  } catch {
    error.value = FAILED
  } finally {
    loading.value = false
  }
}

const submitCredentials = async () => {
  error.value = null
  if (!email.value || !password.value) {
    error.value = 'Укажите email и пароль.'
    return
  }
  loading.value = true
  try {
    await auth.restoreAccount({ email: email.value, password: password.value })
    await finish()
  } catch {
    error.value = FAILED
  } finally {
    loading.value = false
  }
}

// The link is meant to be one click: try it as soon as the page opens, and fall
// back to the credentials form if it fails.
onMounted(() => {
  restoreScroll()
  if (token.value) submitToken()
})
</script>

<template>
  <div class="px-6 py-12 sm:py-16 flex justify-center">
    <div class="w-full max-w-sm">
      <div class="mb-6 text-center">
        <div class="mb-3 flex justify-center">
          <AppLogo :with-text="false" size="lg" />
        </div>
        <h1 class="text-xl font-semibold text-gray-900">Восстановление аккаунта</h1>
        <p class="mt-1 text-sm text-gray-500">
          Вернём доступ и все ваши курсы — пока не истёк срок восстановления
        </p>
      </div>

      <div class="rounded-2xl border border-gray-100 bg-white p-8 shadow-soft">
        <p v-if="token && loading" class="text-center text-sm text-gray-500">
          Восстанавливаем аккаунт…
        </p>

        <form v-else class="space-y-4" @submit.prevent="submitCredentials">
          <p class="text-sm text-gray-600">
            Введите email и пароль удалённого аккаунта, чтобы восстановить его.
          </p>

          <UiInput
            v-model="email"
            label="Email"
            type="email"
            placeholder="you@example.com"
            autocomplete="email"
          />
          <UiInput
            v-model="password"
            label="Пароль"
            type="password"
            placeholder="••••••••"
            autocomplete="current-password"
          />

          <p
            v-if="error"
            class="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700"
          >
            <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
            <span>{{ error }}</span>
          </p>

          <UiButton type="submit" variant="primary" size="lg" block :loading="loading">
            {{ loading ? 'Восстановление…' : 'Восстановить аккаунт' }}
          </UiButton>
        </form>
      </div>

      <p class="mt-5 text-center text-sm text-gray-500">
        <NuxtLink to="/login" class="font-medium text-violet-700 hover:underline">
          Вернуться ко входу
        </NuxtLink>
      </p>
    </div>
  </div>
</template>
