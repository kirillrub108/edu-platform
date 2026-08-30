<!-- Личные данные: аватар, имя, «о себе». Одна и та же форма на вкладке
     /account?tab=profile и прямо на своей странице /u/{id} — состояние и
     запрос общие, различается только ссылка «Открыть профиль» (на самой
     странице профиля она не нужна). -->
<script setup lang="ts">
import { AlertCircle, CheckCircle2, ExternalLink } from 'lucide-vue-next'

withDefaults(defineProps<{ showProfileLink?: boolean }>(), { showProfileLink: false })

const auth = useAuthStore()
const { user } = storeToRefs(auth)

const fullName = ref('')
const bio = ref('')
const error = ref<string | null>(null)
const saved = ref(false)
const saving = ref(false)

onMounted(async () => {
  try {
    const settings = await auth.fetchProfileSettings()
    fullName.value = settings.full_name ?? ''
    bio.value = settings.bio ?? ''
  } catch {
    error.value = 'Не удалось загрузить профиль.'
  }
})

const save = async () => {
  error.value = null
  saved.value = false
  saving.value = true
  try {
    await auth.updateProfile({ full_name: fullName.value, bio: bio.value })
    saved.value = true
  } catch (e: unknown) {
    error.value =
      (e as { data?: { detail?: string } })?.data?.detail ?? 'Не удалось сохранить профиль.'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div>
    <AvatarUpload :user="user" />

    <form class="mt-6 space-y-4" @submit.prevent="save">
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
        v-if="error"
        class="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700"
      >
        <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
        <span>{{ error }}</span>
      </p>
      <p
        v-if="saved"
        class="flex items-start gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700"
      >
        <CheckCircle2 class="mt-0.5 h-4 w-4 shrink-0" />
        <span>Профиль сохранён.</span>
      </p>

      <div class="flex items-center gap-3">
        <UiButton type="submit" variant="primary" :loading="saving">
          {{ saving ? 'Сохранение…' : 'Сохранить' }}
        </UiButton>
        <NuxtLink
          v-if="showProfileLink && user"
          :to="`/u/${user.id}`"
          class="inline-flex items-center gap-1 text-sm font-medium text-violet-700 hover:underline"
        >
          Открыть профиль
          <ExternalLink class="h-3.5 w-3.5" />
        </NuxtLink>
      </div>
    </form>
  </div>
</template>
