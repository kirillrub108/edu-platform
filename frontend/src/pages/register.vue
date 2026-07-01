<script setup lang="ts">
import { AlertCircle } from 'lucide-vue-next'
import { parseApiError } from '~/composables/useApi'

const auth = useAuthStore()
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

// Both mandatory consents must be ticked before the form may be submitted;
// the marketing opt-in is optional and never gates submission.
const consentsGiven = computed(() => acceptedPrivacy.value && acceptedTerms.value)

const submit = async () => {
  if (!consentsGiven.value) return
  error.value = null
  fieldErrors.value = {}
  loading.value = true
  try {
    await auth.register(email.value, password.value, role.value, fullName.value || undefined, {
      accepted_privacy: acceptedPrivacy.value,
      accepted_terms: acceptedTerms.value,
      accepted_marketing: acceptedMarketing.value,
    })
    await navigateTo(role.value === 'teacher' ? '/dashboard' : '/student/dashboard')
  } catch (e: unknown) {
    const parsed = parseApiError(e)
    fieldErrors.value = parsed.fields
    error.value = parsed.general || null
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
        <h1 class="text-xl font-semibold text-gray-900">Создать аккаунт</h1>
        <p class="mt-1 text-sm text-gray-500">Начните создавать видеолекции бесплатно</p>
      </div>

      <div class="rounded-2xl border border-gray-100 bg-white p-8 shadow-soft">
        <!-- Role toggle -->
        <div class="mb-2 flex overflow-hidden rounded-xl border border-gray-200">
          <button
            type="button"
            class="flex-1 py-2 text-sm font-medium transition-colors"
            :class="role === 'teacher' ? 'bg-violet-700 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'"
            @click="role = 'teacher'"
          >
            Преподаватель
          </button>
          <button
            type="button"
            class="flex-1 py-2 text-sm font-medium transition-colors"
            :class="role === 'student' ? 'bg-violet-700 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'"
            @click="role = 'student'"
          >
            Ученик
          </button>
        </div>
        <p class="mb-5 text-center text-xs text-gray-500">
          <template v-if="role === 'teacher'">Создаёте и публикуете курсы</template>
          <template v-else>Проходите курсы по ссылке от учителя</template>
        </p>

        <form class="space-y-4" @submit.prevent="submit">
          <UiInput
            v-model="fullName"
            label="Имя"
            placeholder="Необязательно"
            :error="fieldErrors.full_name"
            @update:model-value="delete fieldErrors['full_name']"
          />
          <UiInput
            v-model="email"
            label="Email"
            type="email"
            placeholder="you@example.com"
            autocomplete="email"
            :error="fieldErrors.email"
            @update:model-value="delete fieldErrors['email']"
          />
          <UiInput
            v-model="password"
            label="Пароль"
            type="password"
            placeholder="••••••••"
            autocomplete="new-password"
            :hint="fieldErrors.password ? undefined : 'Минимум 8 символов'"
            :error="fieldErrors.password"
            @update:model-value="delete fieldErrors['password']"
          />

          <div class="space-y-2.5 pt-1">
            <label class="flex items-start gap-2.5 text-xs leading-relaxed text-gray-600">
              <input
                v-model="acceptedPrivacy"
                type="checkbox"
                class="mt-0.5 h-4 w-4 shrink-0 rounded border-gray-300 text-violet-600 focus:ring-violet-500/30"
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
            <label class="flex items-start gap-2.5 text-xs leading-relaxed text-gray-600">
              <input
                v-model="acceptedTerms"
                type="checkbox"
                class="mt-0.5 h-4 w-4 shrink-0 rounded border-gray-300 text-violet-600 focus:ring-violet-500/30"
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
          </div>

          <p
            v-if="error"
            class="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700"
          >
            <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
            <span>{{ error }}</span>
          </p>

          <UiButton
            type="submit"
            variant="primary"
            size="lg"
            block
            :loading="loading"
            :disabled="!consentsGiven"
          >
            {{ loading ? 'Создание…' : 'Зарегистрироваться' }}
          </UiButton>

          <p v-if="!consentsGiven" class="text-center text-xs text-gray-400">
            Отметьте оба обязательных согласия, чтобы продолжить
          </p>
        </form>
      </div>

      <p class="mt-5 text-center text-sm text-gray-500">
        Уже есть аккаунт?
        <NuxtLink to="/login" class="font-medium text-violet-700 hover:underline">Войти</NuxtLink>
      </p>
    </div>
  </div>
</template>
