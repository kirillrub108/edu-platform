<script setup lang="ts">
import { Loader2, Trash2, Upload } from 'lucide-vue-next'
import type { UserOut } from '~/stores/auth'

const props = defineProps<{ user: UserOut | null }>()

const auth = useAuthStore()

// Mirrors backend AVATAR_ALLOWED_MIME / AVATAR_MAX_BYTES. Client-side checks are
// a courtesy (instant feedback, no wasted upload) — the server re-validates the
// real file signature regardless.
const ALLOWED_TYPES = ['image/jpeg', 'image/png', 'image/webp']
const MAX_SIZE = 2 * 1024 * 1024

const fileInputRef = ref<HTMLInputElement | null>(null)
const uploading = ref(false)
const removing = ref(false)
const error = ref<string | null>(null)

const busy = computed(() => uploading.value || removing.value)

const pick = () => fileInputRef.value?.click()

const onFileChange = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  // Reset immediately so re-picking the same file fires `change` again.
  input.value = ''
  if (!file) return

  error.value = null
  if (!ALLOWED_TYPES.includes(file.type)) {
    error.value = 'Допустимы только JPEG, PNG или WebP.'
    return
  }
  if (file.size > MAX_SIZE) {
    error.value = 'Файл слишком большой — максимум 2 МБ.'
    return
  }

  uploading.value = true
  try {
    await auth.uploadAvatar(file)
  } catch (e: unknown) {
    const detail = (e as { data?: { detail?: string } })?.data?.detail
    error.value = detail ?? 'Не удалось загрузить изображение.'
  } finally {
    uploading.value = false
  }
}

const remove = async () => {
  error.value = null
  removing.value = true
  try {
    await auth.deleteAvatar()
  } catch (e: unknown) {
    const detail = (e as { data?: { detail?: string } })?.data?.detail
    error.value = detail ?? 'Не удалось удалить аватар.'
  } finally {
    removing.value = false
  }
}
</script>

<template>
  <div>
    <span class="mb-2 block text-sm font-medium text-gray-700">Аватар</span>

    <div class="flex items-center gap-4">
      <div class="relative">
        <UserAvatar :user="props.user" size="lg" />
        <div
          v-if="busy"
          class="absolute inset-0 grid place-items-center rounded-full bg-white/70"
        >
          <Loader2 class="h-5 w-5 animate-spin text-violet-700" />
        </div>
      </div>

      <div class="flex flex-col gap-2">
        <div class="flex flex-wrap gap-2">
          <UiButton type="button" variant="secondary" size="sm" :disabled="busy" @click="pick">
            <Upload class="mr-1.5 h-4 w-4" />
            Загрузить
          </UiButton>
          <UiButton
            v-if="props.user?.avatar_url"
            type="button"
            variant="ghost"
            size="sm"
            :disabled="busy"
            @click="remove"
          >
            <Trash2 class="mr-1.5 h-4 w-4" />
            Удалить
          </UiButton>
        </div>
        <p class="text-xs text-gray-500">
          JPEG, PNG или WebP, до 2 МБ.
        </p>
      </div>
    </div>

    <input
      ref="fileInputRef"
      type="file"
      accept="image/jpeg,image/png,image/webp"
      class="hidden"
      @change="onFileChange"
    />

    <p v-if="error" class="mt-2 text-sm text-rose-600">{{ error }}</p>
  </div>
</template>
