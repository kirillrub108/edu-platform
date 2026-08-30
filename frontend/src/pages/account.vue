<script setup lang="ts">
import { AlertCircle, CheckCircle2, ExternalLink, TriangleAlert } from 'lucide-vue-next'
import type { ProfileVisibility } from '~/stores/auth'
import { NOTIFICATION_CATEGORIES } from '~/stores/notifications'

definePageMeta({ middleware: 'auth' })

const auth = useAuthStore()
const { user } = storeToRefs(auth)

const notifications = useNotificationsStore()
const { settings, loading: loadingSettings, saving, error: settingsError } =
  storeToRefs(notifications)

const TABS = [
  { id: 'profile', label: 'Профиль' },
  { id: 'privacy', label: 'Приватность' },
  { id: 'security', label: 'Безопасность' },
  { id: 'danger', label: 'Удаление аккаунта' },
]
const tab = ref('profile')

onMounted(() => notifications.fetchSettings())

// ── Профиль ──────────────────────────────────────────────────────────────────

const fullName = ref('')
const bio = ref('')
const profileError = ref<string | null>(null)
const profileSaved = ref(false)
const savingProfile = ref(false)

onMounted(async () => {
  try {
    const settings = await auth.fetchProfileSettings()
    fullName.value = settings.full_name ?? ''
    bio.value = settings.bio ?? ''
  } catch {
    profileError.value = 'Не удалось загрузить профиль.'
  }
})

const saveProfile = async () => {
  profileError.value = null
  profileSaved.value = false
  savingProfile.value = true
  try {
    await auth.updateProfile({ full_name: fullName.value, bio: bio.value })
    profileSaved.value = true
  } catch (e: unknown) {
    profileError.value =
      (e as { data?: { detail?: string } })?.data?.detail ?? 'Не удалось сохранить профиль.'
  } finally {
    savingProfile.value = false
  }
}

// ── Приватность ──────────────────────────────────────────────────────────────

const VISIBILITY_OPTIONS: { value: ProfileVisibility; label: string; hint: string }[] = [
  { value: 'public', label: 'Открытый', hint: 'Профиль виден всем, включая незарегистрированных.' },
  {
    value: 'authenticated',
    label: 'Для зарегистрированных',
    hint: 'Профиль видят только авторизованные пользователи.',
  },
  {
    value: 'private',
    label: 'Закрытый',
    hint: 'Профиль видите только вы и преподаватели ваших курсов.',
  },
]

const visibility = ref<ProfileVisibility>('authenticated')
const showStats = ref(false)
const privacyError = ref<string | null>(null)
const savingPrivacy = ref(false)

onMounted(async () => {
  try {
    const p = await auth.fetchPrivacy()
    visibility.value = p.profile_visibility
    showStats.value = p.show_profile_stats
  } catch {
    privacyError.value = 'Не удалось загрузить настройки приватности.'
  }
})

// Saved on change rather than behind a button: both controls are single values
// and the same pattern already governs the notification toggles below.
const savePrivacy = async (patch: {
  profile_visibility?: ProfileVisibility
  show_profile_stats?: boolean
}) => {
  privacyError.value = null
  savingPrivacy.value = true
  try {
    const next = await auth.updatePrivacy(patch)
    visibility.value = next.profile_visibility
    showStats.value = next.show_profile_stats
  } catch {
    privacyError.value = 'Не удалось сохранить настройки.'
  } finally {
    savingPrivacy.value = false
  }
}

// ── Смена пароля ─────────────────────────────────────────────────────────────

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

// ── Удаление аккаунта ────────────────────────────────────────────────────────

const RESTORE_DAYS = 30

const confirmingDelete = ref(false)
const deletePassword = ref('')
const deleteError = ref<string | null>(null)
const deleting = ref(false)

const deleteAccount = async () => {
  deleteError.value = null
  deleting.value = true
  try {
    await auth.deleteAccount(deletePassword.value)
    await navigateTo('/login?deleted=1')
  } catch (e: unknown) {
    const err = e as { response?: { status?: number }; data?: { detail?: string } }
    if (err?.data?.detail === 'lessons_in_progress') {
      deleteError.value =
        'Идёт генерация урока. Дождитесь её завершения или отмените, затем повторите.'
    } else if (err?.response?.status === 400) {
      deleteError.value = 'Неверный пароль.'
    } else {
      deleteError.value = err?.data?.detail ?? 'Не удалось удалить аккаунт.'
    }
  } finally {
    deleting.value = false
  }
}
</script>

<template>
  <div class="px-0 sm:px-6 py-8 sm:py-10 flex justify-center">
    <div class="w-full max-w-xl">
      <div class="mb-6">
        <h1 class="text-xl font-semibold text-gray-900">Настройки аккаунта</h1>
        <p class="mt-1 text-sm text-gray-500">{{ user?.email }}</p>
      </div>

      <UiTabs v-model="tab" :tabs="TABS" />

      <!-- Профиль -->
      <div v-if="tab === 'profile'" class="rounded-2xl border border-gray-100 bg-white p-6 sm:p-8 shadow-soft">
        <AvatarUpload :user="user" />

        <form class="mt-6 space-y-4" @submit.prevent="saveProfile">
          <UiInput v-model="fullName" label="Имя" placeholder="Как вас зовут" />
          <UiInput
            v-model="bio"
            label="О себе"
            as="textarea"
            :rows="4"
            placeholder="Пара слов о вас — это видят посетители профиля"
            hint="До 1000 символов"
          />

          <p
            v-if="profileError"
            class="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700"
          >
            <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
            <span>{{ profileError }}</span>
          </p>
          <p
            v-if="profileSaved"
            class="flex items-start gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700"
          >
            <CheckCircle2 class="mt-0.5 h-4 w-4 shrink-0" />
            <span>Профиль сохранён.</span>
          </p>

          <div class="flex items-center gap-3">
            <UiButton type="submit" variant="primary" :loading="savingProfile">
              {{ savingProfile ? 'Сохранение…' : 'Сохранить' }}
            </UiButton>
            <NuxtLink
              v-if="user"
              :to="`/u/${user.id}`"
              class="inline-flex items-center gap-1 text-sm font-medium text-violet-700 hover:underline"
            >
              Открыть профиль
              <ExternalLink class="h-3.5 w-3.5" />
            </NuxtLink>
          </div>
        </form>
      </div>

      <!-- Приватность -->
      <div v-else-if="tab === 'privacy'" class="rounded-2xl border border-gray-100 bg-white p-6 sm:p-8 shadow-soft">
        <h2 class="mb-1 text-base font-semibold text-gray-900">Кто видит профиль</h2>
        <p class="mb-4 text-sm text-gray-500">
          Почта и платёжные данные не показываются в профиле никогда.
        </p>

        <div class="space-y-2">
          <label
            v-for="opt in VISIBILITY_OPTIONS"
            :key="opt.value"
            class="flex cursor-pointer items-start gap-3 rounded-xl border px-4 py-3 transition-colors"
            :class="visibility === opt.value ? 'border-violet-300 bg-violet-50' : 'border-gray-100 hover:bg-gray-50'"
          >
            <input
              type="radio"
              class="mt-1 h-4 w-4 shrink-0 accent-violet-600"
              :value="opt.value"
              :checked="visibility === opt.value"
              :disabled="savingPrivacy"
              @change="savePrivacy({ profile_visibility: opt.value })"
            />
            <span>
              <span class="block text-sm font-medium text-gray-900">{{ opt.label }}</span>
              <span class="block text-sm text-gray-500">{{ opt.hint }}</span>
            </span>
          </label>
        </div>

        <label
          class="mt-4 flex cursor-pointer items-start gap-3 rounded-xl border border-gray-100 px-4 py-3 transition-colors hover:bg-gray-50"
        >
          <input
            type="checkbox"
            class="mt-1 h-4 w-4 shrink-0 accent-violet-600"
            :checked="showStats"
            :disabled="savingPrivacy"
            @change="savePrivacy({ show_profile_stats: ($event.target as HTMLInputElement).checked })"
          />
          <span>
            <span class="block text-sm font-medium text-gray-900">Показывать статистику</span>
            <span class="block text-sm text-gray-500">
              Числа в профиле. Вы видите свою статистику всегда, даже если выключено.
            </span>
          </span>
        </label>

        <p
          v-if="privacyError"
          class="mt-3 flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700"
        >
          <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
          <span>{{ privacyError }}</span>
        </p>
      </div>

      <!-- Безопасность -->
      <template v-else-if="tab === 'security'">
        <div class="rounded-2xl border border-gray-100 bg-white p-6 sm:p-8 shadow-soft">
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

        <div class="mt-6 rounded-2xl border border-gray-100 bg-white p-6 sm:p-8 shadow-soft">
          <h2 class="mb-1 text-base font-semibold text-gray-900">Уведомления на почту</h2>
          <p class="mb-4 text-sm text-gray-500">
            Письма о подтверждении почты и сбросе пароля приходят всегда.
          </p>

          <p v-if="loadingSettings && !settings" class="text-sm text-gray-500">Загрузка…</p>

          <div v-else-if="settings" class="space-y-3">
            <label
              v-for="cat in NOTIFICATION_CATEGORIES"
              :key="cat.key"
              class="flex cursor-pointer items-start gap-3 rounded-xl border border-gray-100 px-4 py-3 transition-colors hover:bg-gray-50"
            >
              <input
                type="checkbox"
                class="mt-1 h-4 w-4 shrink-0 accent-violet-600"
                :checked="settings[cat.key]"
                :disabled="saving === cat.key"
                @change="
                  notifications.setCategory(cat.key, ($event.target as HTMLInputElement).checked)
                "
              />
              <span>
                <span class="block text-sm font-medium text-gray-900">{{ cat.label }}</span>
                <span class="block text-sm text-gray-500">{{ cat.hint }}</span>
              </span>
            </label>
          </div>

          <p
            v-if="settingsError"
            class="mt-3 flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700"
          >
            <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
            <span>{{ settingsError }}</span>
          </p>
        </div>
      </template>

      <!-- Удаление аккаунта -->
      <div v-else-if="tab === 'danger'" class="rounded-2xl border border-rose-200 bg-white p-6 sm:p-8 shadow-soft">
        <h2 class="mb-1 flex items-center gap-2 text-base font-semibold text-rose-700">
          <TriangleAlert class="h-4 w-4" />
          Удаление аккаунта
        </h2>
        <p class="mb-4 text-sm text-gray-600">
          Аккаунт будет отключён, а вход прекратится сразу. Данные сохраняются
          <strong>{{ RESTORE_DAYS }} дней</strong> — в течение этого срока аккаунт можно
          восстановить по ссылке из письма или по email и паролю. Всё это время адрес остаётся
          занятым; освободить его раньше можно отдельной ссылкой из письма.
          После {{ RESTORE_DAYS }} дней данные обезличиваются безвозвратно.
        </p>

        <UiButton
          v-if="!confirmingDelete"
          type="button"
          variant="danger"
          @click="confirmingDelete = true"
        >
          Удалить аккаунт
        </UiButton>

        <form v-else class="space-y-4" @submit.prevent="deleteAccount">
          <UiInput
            v-model="deletePassword"
            label="Подтвердите паролем"
            type="password"
            placeholder="••••••••"
            autocomplete="current-password"
          />

          <p
            v-if="deleteError"
            class="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700"
          >
            <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
            <span>{{ deleteError }}</span>
          </p>

          <div class="flex gap-2">
            <UiButton
              type="submit"
              variant="danger"
              :loading="deleting"
              :disabled="!deletePassword"
            >
              {{ deleting ? 'Удаление…' : 'Да, удалить аккаунт' }}
            </UiButton>
            <UiButton type="button" variant="ghost" @click="confirmingDelete = false">
              Отмена
            </UiButton>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>
