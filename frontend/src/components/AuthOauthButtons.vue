<script setup lang="ts">
import type { OAuthProvider } from '~/stores/auth'

const props = defineProps<{ next?: string }>()

const auth = useAuthStore()
const pending = ref<OAuthProvider | null>(null)
const error = ref<string | null>(null)

// A disabled provider answers 404 — surface it plainly instead of a dead button.
const go = async (provider: OAuthProvider) => {
  if (pending.value) return
  error.value = null
  pending.value = provider
  try {
    await auth.oauthStart(provider, props.next)
  } catch (e: unknown) {
    const status = (e as { response?: { status?: number } })?.response?.status
    error.value =
      status === 404
        ? 'Этот способ входа сейчас недоступен'
        : 'Не удалось начать вход, попробуйте позже'
    pending.value = null
  }
}
</script>

<template>
  <div class="space-y-3">
    <div class="flex items-center gap-3">
      <span class="h-px flex-1 bg-gray-200" />
      <span class="text-xs uppercase tracking-wide text-gray-400">или</span>
      <span class="h-px flex-1 bg-gray-200" />
    </div>

    <UiButton
      variant="secondary"
      size="lg"
      block
      :loading="pending === 'google'"
      :disabled="!!pending"
      @click="go('google')"
    >
      <template #icon>
        <svg class="h-5 w-5" viewBox="0 0 24 24" aria-hidden="true">
          <path fill="#4285F4" d="M23 12.27c0-.85-.08-1.67-.22-2.45H12v4.63h6.17a5.28 5.28 0 0 1-2.29 3.46v2.88h3.7C21.72 18.79 23 15.545 23 12.27Z" />
          <path fill="#34A853" d="M12 23.5c3.1 0 5.7-1.03 7.6-2.79l-3.71-2.88c-1.03.69-2.35 1.1-3.89 1.1-2.99 0-5.52-2.02-6.43-4.73H1.74v2.97A11.5 11.5 0 0 0 12 23.5Z" />
          <path fill="#FBBC05" d="M5.57 14.2a6.9 6.9 0 0 1 0-4.4V6.83H1.74a11.5 11.5 0 0 0 0 10.34l3.83-2.97Z" />
          <path fill="#EA4335" d="M12 5.07c1.69 0 3.2.58 4.4 1.72l3.29-3.29C17.7 1.63 15.1.5 12 .5A11.5 11.5 0 0 0 1.74 6.83l3.83 2.97C6.48 7.09 9.01 5.07 12 5.07Z" />
        </svg>
      </template>
      Продолжить с Google
    </UiButton>

    <UiButton
      variant="secondary"
      size="lg"
      block
      :loading="pending === 'yandex'"
      :disabled="!!pending"
      @click="go('yandex')"
    >
      <template #icon>
        <!-- Официальный контур Яндекса (src/public/yandex-id.svg): диск с
             вырезанной буквой, поэтому «Я» — это дырка, а не белая заливка. -->
        <img src="/yandex-id.svg" alt="" class="h-5 w-5" />
      </template>
      Продолжить с Яндекс ID
    </UiButton>

    <p v-if="error" class="text-center text-xs text-rose-600">{{ error }}</p>
  </div>
</template>
