<script setup lang="ts">
import { CheckCircle2, AlertCircle } from 'lucide-vue-next'

// Public on purpose: the unsubscribe link is clicked straight from an email
// client, with no session. No `auth` middleware here.
const route = useRoute()

const status = computed(() => String(route.query.status ?? 'invalid'))
const ok = computed(() => status.value === 'ok')

const message = computed(() => {
  switch (status.value) {
    case 'ok':
      return 'Вы отписались от этой категории уведомлений. Письма о подтверждении почты и сбросе пароля будут приходить по-прежнему.'
    case 'expired':
      return 'Срок действия ссылки истёк. Отключить уведомления можно в настройках аккаунта.'
    default:
      return 'Ссылка недействительна. Отключить уведомления можно в настройках аккаунта.'
  }
})
</script>

<template>
  <div class="flex min-h-screen items-center justify-center px-4 py-12">
    <div class="w-full max-w-md rounded-2xl border border-gray-100 bg-white p-8 shadow-soft">
      <component
        :is="ok ? CheckCircle2 : AlertCircle"
        class="h-10 w-10"
        :class="ok ? 'text-emerald-500' : 'text-amber-500'"
      />
      <h1 class="mt-4 text-xl font-semibold text-gray-900">
        {{ ok ? 'Уведомления отключены' : 'Не удалось отписаться' }}
      </h1>
      <p class="mt-2 text-sm text-gray-600">{{ message }}</p>
      <NuxtLink to="/account" class="mt-6 inline-block">
        <UiButton variant="secondary" size="md">Настройки аккаунта</UiButton>
      </NuxtLink>
    </div>
  </div>
</template>
