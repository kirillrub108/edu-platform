<script setup lang="ts">
const auth = useAuthStore()
const email = ref('')
const password = ref('')
const rememberMe = ref(true)
const error = ref<string | null>(null)
const loading = ref(false)

const submit = async () => {
  error.value = null
  loading.value = true
  try {
    await auth.login(email.value, password.value, rememberMe.value)
    const dest = auth.user?.role === 'student' ? '/student/dashboard' : '/dashboard'
    await navigateTo(dest)
  } catch (e: any) {
    error.value = e?.data?.detail ?? 'Неверный email или пароль'
  } finally {
    loading.value = false
  }
}

onMounted(restoreScroll)
</script>

<template>
  <div class="max-w-sm mx-auto">
    <div class="bg-white p-8 rounded-xl border border-gray-200 shadow-sm">
      <h1 class="text-xl font-semibold mb-6 text-center">Вход</h1>

      <form class="space-y-3" @submit.prevent="submit">
        <input
          v-model="email"
          type="email"
          placeholder="Email"
          required
          autocomplete="email"
          class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
        />
        <input
          v-model="password"
          type="password"
          placeholder="Пароль"
          required
          autocomplete="current-password"
          class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
        />

        <label class="flex items-center gap-2 text-sm text-gray-600 select-none cursor-pointer ml-1">
          <input
            v-model="rememberMe"
            type="checkbox"
            class="h-4 w-4 rounded accent-brand cursor-pointer"
          />
          Запомнить меня
        </label>

        <p v-if="error" class="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">
          {{ error }}
        </p>

        <button
          type="submit"
          :disabled="loading"
          class="w-full bg-brand text-white rounded-lg py-2 font-medium disabled:opacity-50 transition"
        >
          {{ loading ? 'Вход…' : 'Войти' }}
        </button>
      </form>

      <p class="text-center text-sm text-gray-500 mt-4">
        Нет аккаунта?
        <NuxtLink to="/register" class="text-brand hover:underline">Зарегистрироваться</NuxtLink>
      </p>
    </div>
  </div>
</template>
