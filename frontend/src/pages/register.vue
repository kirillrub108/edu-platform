<script setup lang="ts">
import { AlertCircle } from 'lucide-vue-next'
import { parseApiError } from '~/composables/useApi'

definePageMeta({ middleware: ['guest'] })

const route = useRoute()
const auth = useAuthStore()
const { reachGoal } = useMetrika()
const email = ref('')
const password = ref('')
const fullName = ref('')
const role = ref<'teacher' | 'student'>('teacher')
const acceptedPrivacy = ref(false)
const acceptedTerms = ref(false)
const acceptedMarketing = ref(false)
const error = ref<string | null>(null)
const fieldErrors = ref<Record<string, string>>({})
const loading = ref(false)
const { remaining: cooldownRemaining, triggerFrom429 } = useRateLimitCooldown()

// Both mandatory consents must be ticked before the form may be submitted;
// the marketing opt-in is optional and never gates submission.
const consentsGiven = computed(() => acceptedPrivacy.value && acceptedTerms.value)
// Set only after a failed submit attempt, so the checkboxes don't start red.
const consentAttempted = ref(false)

const fullNameHint = computed(() => {
  const remaining = FULL_NAME_MAX_LENGTH - fullName.value.length
  return remaining <= 50 ? `Осталось ${remaining} симв.` : undefined
})

const normalizeEmail = () => {
  email.value = normalizeEmailDomain(email.value)
}

// Client-side pass so errors show inline in every browser (not just via a
// native :invalid tooltip, which Firefox renders differently and which
// firing at submit-time bypasses our own submit handler). The server 422
// path (parseApiError above) stays the authoritative fallback.
const validate = (): boolean => {
  fieldErrors.value = {}
  if (!email.value.trim()) {
    fieldErrors.value.email = 'Обязательное поле'
  } else if (!isValidEmail(email.value)) {
    fieldErrors.value.email = 'Некорректный email'
  }
  if (!password.value.trim()) {
    fieldErrors.value.password = 'Пароль не может состоять только из пробелов'
  } else if (password.value.length < PASSWORD_MIN_LENGTH) {
    fieldErrors.value.password = `Минимум ${PASSWORD_MIN_LENGTH} символов`
  }
  return Object.keys(fieldErrors.value).length === 0
}

// Coming back from an OAuth callback with an unknown identity: the account does
// not exist yet, only a one-shot ticket. Role + consents are still ours to
// collect, so the same form runs without the email/password fields.
const oauthTicket = computed(() => (route.query.oauth_pending as string | undefined) || null)
const oauthProvider = computed(() => (route.query.provider as string | undefined) || null)
const providerLabel = computed(() =>
  oauthProvider.value === 'yandex' ? 'Яндекс ID' : 'Google',
)

const completeOauth = async (ticket: string) => {
  const redirect = await auth.oauthComplete(ticket, role.value, {
    pdn_consent: acceptedPrivacy.value,
    offer_consent: acceptedTerms.value,
    marketing_consent: acceptedMarketing.value,
  })
  reachGoal(METRIKA_GOALS.signup, { role: role.value })
  await navigateTo(redirect)
}

const submit = async () => {
  if (loading.value || cooldownRemaining.value > 0) return
  if (!consentsGiven.value) {
    consentAttempted.value = true
    return
  }
  const ticket = oauthTicket.value
  if (!ticket && !validate()) return

  error.value = null
  loading.value = true
  try {
    if (ticket) {
      await completeOauth(ticket)
      return
    }
    await auth.register(
      email.value,
      password.value,
      role.value,
      fullName.value.trim() || undefined,
      {
        accepted_privacy: acceptedPrivacy.value,
        accepted_terms: acceptedTerms.value,
        accepted_marketing: acceptedMarketing.value,
      },
    )
    reachGoal(METRIKA_GOALS.signup, { role: role.value })
    await navigateTo(role.value === 'teacher' ? '/dashboard' : '/student/dashboard')
  } catch (e: unknown) {
    // The address belongs to an account still inside its restore window, so it
    // is not free yet. Offer the release flow instead of a dead-end error.
    if (parsePendingDeletion(e, 409)) {
      pendingDeletion.value = true
      error.value = null
      fieldErrors.value = {}
      return
    }
    if ((e as { response?: { status?: number } })?.response?.status === 429) {
      triggerFrom429(e)
    }
    const parsed = parseApiError(e)
    fieldErrors.value = parsed.fields
    error.value = parsed.general || null
  } finally {
    loading.value = false
  }
}

const pendingDeletion = ref(false)
const releaseRequested = ref(false)
const releasing = ref(false)

// Always 204 server-side, so there is no failure branch worth showing: the
// message is the same whether or not a letter actually went out.
const requestRelease = async () => {
  releasing.value = true
  try {
    await auth.requestEmailRelease(email.value)
  } catch {
    /* noop - the endpoint is deliberately opaque */
  } finally {
    releasing.value = false
    releaseRequested.value = true
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
        <h1 class="text-xl font-semibold text-gray-900">
          {{ oauthTicket ? 'Почти готово' : 'Создать аккаунт' }}
        </h1>
        <p class="mt-1 text-sm text-gray-500">
          <template v-if="oauthTicket">
            Вы вошли через {{ providerLabel }}. Осталось выбрать роль и принять условия
          </template>
          <template v-else>Начните создавать видеоуроки бесплатно</template>
        </p>
      </div>

      <div class="rounded-2xl border border-gray-100 bg-white p-6 sm:p-8 shadow-soft">
        <!-- Role toggle -->
        <div class="mb-2 flex overflow-hidden rounded-xl border border-gray-200">
          <button
            type="button"
            class="flex-1 py-2 text-sm font-medium transition-colors"
            :class="role === 'teacher' ? 'bg-violet-700 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'"
            @click="role = 'teacher'"
          >
            Автор
          </button>
          <button
            type="button"
            class="flex-1 py-2 text-sm font-medium transition-colors"
            :class="role === 'student' ? 'bg-violet-700 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'"
            @click="role = 'student'"
          >
            Студент
          </button>
        </div>
        <p class="mb-5 text-center text-xs text-gray-500">
          <template v-if="role === 'teacher'">Создаёте и публикуете курсы</template>
          <template v-else>Проходите курсы по ссылке от автора</template>
        </p>

        <form class="space-y-4" novalidate @submit.prevent="submit">
          <UiInput
            v-if="!oauthTicket"
            v-model="fullName"
            label="Имя"
            optional
            placeholder="Иван Иванов"
            :maxlength="FULL_NAME_MAX_LENGTH"
            :hint="fieldErrors.full_name ? undefined : fullNameHint"
            :error="fieldErrors.full_name"
            @update:model-value="delete fieldErrors['full_name']"
          />
          <UiInput
            v-if="!oauthTicket"
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
            v-if="!oauthTicket"
            v-model="password"
            label="Пароль"
            type="password"
            placeholder="••••••••"
            autocomplete="new-password"
            :hint="fieldErrors.password ? undefined : `Минимум ${PASSWORD_MIN_LENGTH} символов`"
            :error="fieldErrors.password"
            @update:model-value="delete fieldErrors['password']"
          />

          <div class="space-y-2.5 pt-1">
            <label
              class="flex items-start gap-2.5 text-xs leading-relaxed"
              :class="consentAttempted && !acceptedPrivacy ? 'text-rose-700' : 'text-gray-600'"
            >
              <input
                v-model="acceptedPrivacy"
                type="checkbox"
                class="mt-0.5 h-4 w-4 shrink-0 rounded focus:ring-violet-500/30"
                :class="consentAttempted && !acceptedPrivacy
                  ? 'border-rose-400 text-rose-600'
                  : 'border-gray-300 text-violet-600'"
              />
              <span>
                Я даю
                <NuxtLink
                  to="/legal/pdn-consent"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="font-medium text-violet-700 hover:underline"
                >согласие на обработку персональных данных</NuxtLink>
                и принимаю
                <NuxtLink
                  to="/legal/privacy"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="font-medium text-violet-700 hover:underline"
                >Политику конфиденциальности</NuxtLink>
              </span>
            </label>
            <label
              class="flex items-start gap-2.5 text-xs leading-relaxed"
              :class="consentAttempted && !acceptedTerms ? 'text-rose-700' : 'text-gray-600'"
            >
              <input
                v-model="acceptedTerms"
                type="checkbox"
                class="mt-0.5 h-4 w-4 shrink-0 rounded focus:ring-violet-500/30"
                :class="consentAttempted && !acceptedTerms
                  ? 'border-rose-400 text-rose-600'
                  : 'border-gray-300 text-violet-600'"
              />
              <span>
                Я принимаю условия
                <NuxtLink
                  to="/legal/offer"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="font-medium text-violet-700 hover:underline"
                >Публичной оферты</NuxtLink>
              </span>
            </label>
            <label class="flex items-start gap-2.5 text-xs leading-relaxed text-gray-600">
              <input
                v-model="acceptedMarketing"
                type="checkbox"
                class="mt-0.5 h-4 w-4 shrink-0 rounded border-gray-300 text-violet-600 focus:ring-violet-500/30"
              />
              <span>Согласен(на) получать новостные и рекламные рассылки</span>
            </label>
            <p
              v-if="consentAttempted && !consentsGiven"
              class="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700"
            >
              <AlertCircle class="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>Отметьте оба обязательных согласия, чтобы продолжить</span>
            </p>
          </div>

          <p
            v-if="error"
            class="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700"
          >
            <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
            <span>{{ error }}</span>
          </p>

          <div
            v-if="pendingDeletion"
            class="rounded-xl border border-amber-200 bg-amber-50 px-3 py-3 text-sm text-amber-900"
          >
            <p class="flex items-start gap-2">
              <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
              <span>
                Этот адрес занят удалённым аккаунтом, который ещё можно восстановить.
              </span>
            </p>

            <p v-if="releaseRequested" class="mt-2">
              Если адрес действительно ваш, мы отправили на него письмо со ссылкой для
              освобождения. После подтверждения старый аккаунт восстановить будет нельзя.
            </p>
            <template v-else>
              <p class="mt-2">
                Если это ваш аккаунт, войдите и восстановите его — или освободите адрес, чтобы
                зарегистрировать новый.
              </p>
              <div class="mt-2 flex flex-wrap gap-2">
                <NuxtLink
                  to="/restore-account"
                  class="inline-block rounded-xl border border-amber-300 px-4 py-2 text-sm font-medium text-amber-900 transition hover:bg-amber-100"
                >
                  Восстановить аккаунт
                </NuxtLink>
                <UiButton
                  type="button"
                  variant="secondary"
                  size="sm"
                  :loading="releasing"
                  @click="requestRelease"
                >
                  Это мой адрес, освободить его
                </UiButton>
              </div>
            </template>
          </div>

          <UiButton
            type="submit"
            variant="primary"
            size="lg"
            block
            :loading="loading"
            :disabled="cooldownRemaining > 0"
          >
            <template v-if="loading">Создание…</template>
            <template v-else-if="cooldownRemaining > 0">Подождите {{ cooldownRemaining }} с</template>
            <template v-else-if="oauthTicket">Завершить регистрацию</template>
            <template v-else>Зарегистрироваться</template>
          </UiButton>
        </form>

        <AuthOauthButtons v-if="!oauthTicket" class="mt-5" />
      </div>

      <p class="mt-5 text-center text-sm text-gray-500">
        Уже есть аккаунт?
        <NuxtLink to="/login" class="font-medium text-violet-700 hover:underline">Войти</NuxtLink>
      </p>
    </div>
  </div>
</template>
