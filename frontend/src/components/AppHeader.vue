<script setup lang="ts">
const { user, isAuthenticated, logout, fetchMe } = useAuth()

onMounted(() => {
  if (!user.value) fetchMe()
})
</script>

<template>
  <header class="bg-white border-b border-gray-200">
    <div class="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
      <NuxtLink to="/" class="font-semibold text-brand text-lg">Edu Platform</NuxtLink>

      <nav class="flex items-center gap-5 text-sm">
        <template v-if="isAuthenticated">
          <NuxtLink
            v-if="user?.role === 'teacher'"
            to="/dashboard"
            class="text-gray-700 hover:text-brand transition"
          >
            Мои курсы
          </NuxtLink>
          <NuxtLink
            v-else
            to="/student/dashboard"
            class="text-gray-700 hover:text-brand transition"
          >
            Мои курсы
          </NuxtLink>

          <span class="text-gray-400 text-xs">
            {{ user?.full_name || user?.email }}
            <span class="ml-1 px-1.5 py-0.5 rounded text-[10px] font-medium"
              :class="user?.role === 'teacher' ? 'bg-indigo-50 text-indigo-600' : 'bg-green-50 text-green-600'"
            >
              {{ user?.role === 'teacher' ? 'Преподаватель' : 'Студент' }}
            </span>
          </span>

          <button class="text-gray-500 hover:text-red-500 transition text-xs" @click="logout">
            Выйти
          </button>
        </template>

        <template v-else>
          <NuxtLink to="/login" class="text-gray-700 hover:text-brand transition">Войти</NuxtLink>
          <NuxtLink
            to="/register"
            class="px-3 py-1.5 bg-brand text-white rounded-lg text-sm font-medium hover:opacity-90 transition"
          >
            Регистрация
          </NuxtLink>
        </template>
      </nav>
    </div>
  </header>
</template>
