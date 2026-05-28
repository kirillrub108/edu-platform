<script setup lang="ts">
import { GraduationCap, LogOut, Menu } from 'lucide-vue-next'

const auth = useAuthStore()
const { user, isAuthenticated } = storeToRefs(auth)
const { logout } = auth

onMounted(() => {
  if (!user.value) auth.fetchMe()
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
          EduAI
        </span>
      </NuxtLink>

<div v-if="isAuthenticated" class="hidden md:flex items-center gap-3">
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
          Начать бесплатно
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
