<script setup lang="ts">
import { AlertCircle } from 'lucide-vue-next'

definePageMeta({ middleware: ['guest'] })

const route = useRoute()
const auth = useAuthStore()
const email = ref('')
const password = ref('')
const rememberMe = ref(true)
const error = ref<string | null>(null)
const loading = ref(false)
const fieldErrors = ref<Record<string, string>>({})
const { remaining: cooldownRemaining, triggerFrom429 } = useRateLimitCooldown()

const normalizeEmail = () => {
  email.value = normalizeEmailDomain(email.value)
}

// Same client-side pass as register.vue: inline errors in every browser
// instead of relying on the native :invalid tooltip.
const validate = (): boolean => {
  fieldErrors.value = {}
  if (!email.value.trim()) {
    fieldErrors.value.email = 'Обязательное поле'
  } else if (!isValidEmail(email.value)) {
    fieldErrors.value.email = 'Некорректный email'
  }
  if (!password.value) {
    fieldErrors.value.password = 'Обязательное поле'
  }
  return Object.keys(fieldErrors.value).length === 0
}

// Reason codes the OAuth callback appends when sign-in could not complete.
const justDeleted = ref(false)

const OAUTH_REASONS: Record<string, string> = {
  access_denied: 'Вы отменили вход через провайдера',
  email_unverified: 'Провайдер не подтвердил ваш email — войдите по паролю',
  no_email: 'Провайдер не передал email — войдите по паролю',
  email_not_allowed: 'Этот почтовый домен не поддерживается',
  account_disabled: 'Аккаунт отключён. Обратитесь в поддержку',
  account_conflict: 'К этому email уже привязан другой аккаунт провайдера',
  invalid_state: 'Сессия входа устарела, попробуйте ещё раз',
  invalid_request: 'Некорректный ответ провайдера, попробуйте ещё раз',
  provider_unreachable: 'Провайдер недоступен, попробуйте позже',
  provider_error: 'Провайдер вернул ошибку, попробуйте позже',
  internal_error: 'Не удалось завершить вход, попробуйте позже',
}

// Arrived here right after deleting the account.
if (route.query.deleted === '1') {
  justDeleted.value = true
}

if (route.query.oauth === '0') {
  const reason = route.query.reason as string | undefined
  error.value = (reason && OAUTH_REASONS[reason]) || 'Не удалось войти через провайдера'
}

// Set when the password was right but the account is inside its restore
// window: the server only says so after proving the password, so showing the
// recovery CTA here leaks nothing.
const pendingDeletionUntil = ref<string | null>(null)
const showRestoreCta = ref(false)

const submit = async () => {
  if (loading.value || cooldownRemaining.value > 0) return
  if (!validate()) return

  error.value = null
  showRestoreCta.value = false
  loading.value = true
  try {
    await auth.login(email.value, password.value, rememberMe.value)
    const redirect = route.query.redirect as string | undefined
    const dest = redirect || (auth.user?.role === 'student' ? '/student/dashboard' : '/dashboard')
    await navigateTo(dest)
  } catch (e: any) {
    if (e?.response?.status === 429) {
      triggerFrom429(e)
      error.value = 'Слишком много попыток, попробуйте позже'
      return
    }
    const pending = parsePendingDeletion(e, 403)
    if (pending) {
      showRestoreCta.value = true
      pendingDeletionUntil.value = formatRestoreDeadline(pending.restoreUntil)
      error.value = null
    } else {
      error.value = e?.data?.detail ?? 'Неверный email или пароль'
    }
  } finally {
    loading.value = false
  }
}

onMounted(restoreScroll)
</script>

<template>
  <div class="px-0 sm:px-6 py-10 sm:py-16 flex justify-center">
    <div class="w-full max-w-sm">
      <div class="mb-6 text-center">
        <div class="mb-3 flex justify-center">
          <AppLogo :with-text="false" size="lg" />
        </div>
        <h1 class="text-xl font-semibold text-gray-900">С возвращением</h1>
        <p class="mt-1 text-sm text-gray-500">Войдите, чтобы продолжить в Edllm</p>
      </div>

      <div class="rounded-2xl border border-gray-100 bg-white p-6 sm:p-8 shadow-soft">
        <p
          v-if="justDeleted"
          class="mb-4 rounded-xl border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-600"
        >
          Аккаунт удалён. Мы отправили на почту ссылку для восстановления — она действует 30 дней.
        </p>

        <form class="space-y-4" novalidate @submit.prevent="submit">
          <UiInput
            v-model="email"
            label="Email"
            type="email"
            placeholder="you@example.com"
            autocomplete="email"
            :error="fieldErrors.email"
            @update:model-value="delete fieldErrors['email']"
            @blur="normalizeEmail"
          />
          <UiInput
            v-model="password"
            label="Пароль"
            type="password"
            placeholder="••••••••"
            autocomplete="current-password"
            :error="fieldErrors.password"
            @update:model-value="delete fieldErrors['password']"
          />

          <div class="flex items-center justify-between">
            <label class="flex cursor-pointer select-none items-center gap-2 text-sm text-gray-600">
              <input v-model="rememberMe" type="checkbox" class="h-4 w-4 rounded accent-violet-600 cursor-pointer" />
              Запомнить меня
            </label>
            <NuxtLink to="/forgot-password" class="text-sm font-medium text-violet-700 hover:underline">
              Забыли пароль?
            </NuxtLink>
          </div>

          <p
            v-if="error"
            class="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700"
          >
            <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
            <span>{{ error }}</span>
          </p>

          <div
            v-if="showRestoreCta"
            class="rounded-xl border border-amber-200 bg-amber-50 px-3 py-3 text-sm text-amber-900"
          >
            <p class="flex items-start gap-2">
              <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
              <span>
                Этот аккаунт удалён<template v-if="pendingDeletionUntil">, но его ещё можно
                восстановить до {{ pendingDeletionUntil }}</template>.
              </span>
            </p>
            <NuxtLink
              to="/restore-account"
              class="mt-2 inline-block rounded-xl bg-amber-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-amber-500"
            >
              Восстановить аккаунт
            </NuxtLink>
          </div>

          <UiButton
            type="submit"
            variant="primary"
            size="lg"
            block
            :loading="loading"
            :disabled="cooldownRemaining > 0"
          >
            <template v-if="loading">Вход…</template>
            <template v-else-if="cooldownRemaining > 0">Подождите {{ cooldownRemaining }} с</template>
            <template v-else>Войти</template>
          </UiButton>
        </form>

        <AuthOauthButtons class="mt-5" :next="(route.query.redirect as string | undefined)" />
      </div>

      <p class="mt-5 text-center text-sm text-gray-500">
        Нет аккаунта?
        <NuxtLink to="/register" class="font-medium text-violet-700 hover:underline">Зарегистрироваться</NuxtLink>
      </p>
    </div>
  </div>
</template>
