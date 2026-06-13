<script setup lang="ts">
import { AlertCircle } from 'lucide-vue-next'

const route = useRoute()
const auth = useAuthStore()
const email = ref('')
const password = ref('')
const rememberMe = ref(true)
const error = ref<string | null>(null)
const loading = ref(false)

const submit = async () => {
  error.value = null
  loading.value = true
  try {
    await auth.login(email.value, password.value, rememberMe.value)
    const redirect = route.query.redirect as string | undefined
    const dest = redirect || (auth.user?.role === 'student' ? '/student/dashboard' : '/dashboard')
    await navigateTo(dest)
  } catch (e: any) {
    error.value = e?.data?.detail ?? 'Неверный email или пароль'
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
        <h1 class="text-xl font-semibold text-gray-900">С возвращением</h1>
        <p class="mt-1 text-sm text-gray-500">Войдите, чтобы продолжить в Edllm</p>
      </div>

      <div class="rounded-2xl border border-gray-100 bg-white p-8 shadow-soft">
        <form class="space-y-4" @submit.prevent="submit">
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

          <label class="flex cursor-pointer select-none items-center gap-2 text-sm text-gray-600">
            <input v-model="rememberMe" type="checkbox" class="h-4 w-4 rounded accent-violet-600 cursor-pointer" />
            Запомнить меня
          </label>

          <p
            v-if="error"
            class="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700"
          >
            <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
            <span>{{ error }}</span>
          </p>

          <UiButton type="submit" variant="primary" size="lg" block :loading="loading">
            {{ loading ? 'Вход…' : 'Войти' }}
          </UiButton>
        </form>
      </div>

      <p class="mt-5 text-center text-sm text-gray-500">
        Нет аккаунта?
        <NuxtLink to="/register" class="font-medium text-violet-700 hover:underline">Зарегистрироваться</NuxtLink>
      </p>
    </div>
  </div>
</template>
