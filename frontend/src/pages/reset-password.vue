<script setup lang="ts">
import { AlertCircle, CheckCircle2 } from 'lucide-vue-next'

const route = useRoute()
const auth = useAuthStore()

const token = computed(() => {
  const raw = route.query.token
  return Array.isArray(raw) ? raw[0] : raw
})

const password = ref('')
const confirm = ref('')
const error = ref<string | null>(null)
const loading = ref(false)
const done = ref(false)

const submit = async () => {
  error.value = null
  if (!token.value) {
    error.value = 'Ссылка недействительна. Запросите сброс пароля заново.'
    return
  }
  if (password.value.length < 8) {
    error.value = 'Пароль должен содержать не менее 8 символов.'
    return
  }
  if (password.value !== confirm.value) {
    error.value = 'Пароли не совпадают.'
    return
  }
  loading.value = true
  try {
    await auth.resetPassword(token.value, password.value)
    done.value = true
  } catch (e: any) {
    // The server returns one opaque error for any token problem.
    error.value =
      e?.response?.status === 400
        ? 'Ссылка устарела или уже использована. Запросите сброс пароля заново.'
        : (e?.data?.detail ?? 'Не удалось сменить пароль. Попробуйте позже.')
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
        <h1 class="text-xl font-semibold text-gray-900">Новый пароль</h1>
        <p class="mt-1 text-sm text-gray-500">Придумайте новый пароль для входа</p>
      </div>

      <div class="rounded-2xl border border-gray-100 bg-white p-8 shadow-soft">
        <div v-if="done" class="flex flex-col items-center gap-3 text-center">
          <CheckCircle2 class="h-10 w-10 text-emerald-500" />
          <p class="text-sm text-gray-600">Пароль изменён. Теперь войдите с новым паролем.</p>
          <NuxtLink
            to="/login"
            class="inline-block rounded-xl bg-violet-700 px-5 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-violet-600"
          >
            Войти
          </NuxtLink>
        </div>

        <form v-else class="space-y-4" @submit.prevent="submit">
          <UiInput
            v-model="password"
            label="Новый пароль"
            type="password"
            placeholder="••••••••"
            autocomplete="new-password"
            hint="Минимум 8 символов"
          />
          <UiInput
            v-model="confirm"
            label="Повторите пароль"
            type="password"
            placeholder="••••••••"
            autocomplete="new-password"
          />

          <p
            v-if="error"
            class="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700"
          >
            <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
            <span>{{ error }}</span>
          </p>

          <UiButton type="submit" variant="primary" size="lg" block :loading="loading">
            {{ loading ? 'Сохранение…' : 'Сменить пароль' }}
          </UiButton>
        </form>
      </div>

      <p class="mt-5 text-center text-sm text-gray-500">
        <NuxtLink to="/login" class="font-medium text-violet-700 hover:underline">Вернуться ко входу</NuxtLink>
      </p>
    </div>
  </div>
</template>
