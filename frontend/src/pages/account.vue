<script setup lang="ts">
import { AlertCircle, CheckCircle2 } from 'lucide-vue-next'

definePageMeta({ middleware: 'auth' })

const auth = useAuthStore()
const { user } = storeToRefs(auth)

const oldPassword = ref('')
const newPassword = ref('')
const confirm = ref('')
const error = ref<string | null>(null)
const success = ref(false)
const loading = ref(false)

const submit = async () => {
  error.value = null
  success.value = false
  if (newPassword.value.length < 8) {
    error.value = 'Новый пароль должен содержать не менее 8 символов.'
    return
  }
  if (newPassword.value !== confirm.value) {
    error.value = 'Пароли не совпадают.'
    return
  }
  loading.value = true
  try {
    await auth.changePassword(oldPassword.value, newPassword.value)
    success.value = true
    oldPassword.value = ''
    newPassword.value = ''
    confirm.value = ''
  } catch (e: any) {
    error.value =
      e?.response?.status === 400
        ? 'Текущий пароль указан неверно.'
        : (e?.data?.detail ?? 'Не удалось сменить пароль. Попробуйте позже.')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="px-6 py-10 flex justify-center">
    <div class="w-full max-w-md">
      <div class="mb-6">
        <h1 class="text-xl font-semibold text-gray-900">Настройки аккаунта</h1>
        <p class="mt-1 text-sm text-gray-500">{{ user?.email }}</p>
      </div>

      <div class="rounded-2xl border border-gray-100 bg-white p-8 shadow-soft">
        <h2 class="mb-4 text-base font-semibold text-gray-900">Смена пароля</h2>
        <form class="space-y-4" @submit.prevent="submit">
          <UiInput
            v-model="oldPassword"
            label="Текущий пароль"
            type="password"
            placeholder="••••••••"
            autocomplete="current-password"
          />
          <UiInput
            v-model="newPassword"
            label="Новый пароль"
            type="password"
            placeholder="••••••••"
            autocomplete="new-password"
            hint="Минимум 8 символов"
          />
          <UiInput
            v-model="confirm"
            label="Повторите новый пароль"
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
          <p
            v-if="success"
            class="flex items-start gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700"
          >
            <CheckCircle2 class="mt-0.5 h-4 w-4 shrink-0" />
            <span>Пароль изменён. Остальные сессии завершены.</span>
          </p>

          <UiButton type="submit" variant="primary" size="lg" block :loading="loading">
            {{ loading ? 'Сохранение…' : 'Сменить пароль' }}
          </UiButton>
        </form>
      </div>
    </div>
  </div>
</template>
