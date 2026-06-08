<script setup lang="ts">
import { GraduationCap, LogOut, Menu, MailWarning, Coins } from 'lucide-vue-next'

const auth = useAuthStore()
const { user, isAuthenticated, isEmailVerified } = storeToRefs(auth)
const { logout, openVerifyPrompt } = auth

const billing = useBillingStore()
const { available } = storeToRefs(billing)
const isTeacher = computed(() => user.value?.role === 'teacher')

onMounted(async () => {
  if (!user.value) await auth.fetchMe()
  if (isTeacher.value) billing.fetchBalance()
})

// Refresh the balance whenever a teacher session appears (login, reload),
// so the header counter is always current without polling.
watch(() => user.value?.role, (role) => {
  if (role === 'teacher') billing.fetchBalance()
})

const initials = computed(() =>
  (user.value?.full_name || user.value?.email || '?').slice(0, 2).toUpperCase(),
)
const open = ref(false)

const dashboardLink = computed(() =>
  user.value?.role === 'teacher' ? '/dashboard' : '/student/dashboard',
)
</script>

<template>
  <header class="bg-white border-b border-violet-100 sticky top-0 z-30">
    <div class="px-6 h-16 flex items-center justify-between">
      <NuxtLink to="/" class="flex items-center gap-2.5">
        <div class="w-9 h-9 rounded-xl bg-gradient-to-br from-violet-600 to-purple-500 grid place-items-center shadow-sm">
          <GraduationCap class="w-5 h-5 text-white" />
        </div>
        <span class="font-semibold text-lg bg-gradient-to-r from-violet-600 to-purple-500 bg-clip-text text-transparent">
          Edllm
        </span>
      </NuxtLink>

<div v-if="isAuthenticated" class="hidden md:flex items-center gap-3">
        <NuxtLink
          v-if="isTeacher"
          to="/billing"
          class="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold text-violet-700 bg-violet-50 border border-violet-100 hover:bg-violet-100 transition tabular-nums"
          title="Баланс кредитов"
        >
          <Coins class="w-3.5 h-3.5" />
          {{ available }}
        </NuxtLink>
        <button
          v-if="user && !isEmailVerified"
          type="button"
          class="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium text-amber-700 bg-amber-50 border border-amber-200 hover:bg-amber-100 transition"
          title="Подтвердите email, чтобы открыть AI-функции"
          @click="openVerifyPrompt"
        >
          <MailWarning class="w-3.5 h-3.5" />
          Почта не подтверждена
        </button>
        <div class="flex items-center gap-2.5">
          <div class="w-8 h-8 rounded-full bg-violet-100 text-violet-700 grid place-items-center text-xs font-semibold">
            {{ initials }}
          </div>
          <div class="leading-tight">
            <div class="text-sm font-medium text-gray-900">{{ user?.full_name || user?.email }}</div>
            <div class="text-[11px] text-gray-500">
              {{ user?.role === 'teacher' ? 'Преподаватель' : 'Ученик' }}
            </div>
          </div>
        </div>
        <button
          class="w-9 h-9 rounded-lg grid place-items-center text-gray-500 hover:bg-gray-100 hover:text-gray-700 transition"
          aria-label="Выйти"
          @click="logout"
        >
          <LogOut class="w-4 h-4" />
        </button>
      </div>

      <div v-else class="hidden md:flex items-center gap-2">
        <NuxtLink
          to="/login"
          class="px-4 py-2 rounded-xl text-sm font-medium text-gray-700 hover:text-violet-700 transition"
        >
          Войти
        </NuxtLink>
        <NuxtLink
          to="/register"
          class="px-5 py-2.5 rounded-xl text-sm font-medium bg-violet-700 hover:bg-violet-600 text-white shadow-sm transition"
        >
          Создать аккаунт
        </NuxtLink>
      </div>

      <button
        class="md:hidden w-9 h-9 grid place-items-center rounded-lg hover:bg-gray-100"
        aria-label="Меню"
        @click="open = !open"
      >
        <Menu class="w-5 h-5" />
      </button>
    </div>
  </header>
</template>
