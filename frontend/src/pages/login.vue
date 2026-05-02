<script setup lang="ts">
const { login } = useAuth()
const email = ref('')
const password = ref('')
const error = ref<string | null>(null)
const loading = ref(false)

const submit = async () => {
  error.value = null
  loading.value = true
  try {
    await login(email.value, password.value)
    await navigateTo('/dashboard')
  } catch (e: any) {
    error.value = e?.data?.detail ?? 'Login failed'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="max-w-sm mx-auto bg-white p-6 rounded-lg border border-gray-200">
    <h1 class="text-xl font-semibold mb-4">Вход</h1>
    <form class="space-y-3" @submit.prevent="submit">
      <input v-model="email" type="email" placeholder="Email" required class="w-full border rounded px-3 py-2" />
      <input v-model="password" type="password" placeholder="Password" required class="w-full border rounded px-3 py-2" />
      <button :disabled="loading" class="w-full bg-brand text-white rounded py-2">
        {{ loading ? '...' : 'Войти' }}
      </button>
      <p v-if="error" class="text-sm text-red-600">{{ error }}</p>
    </form>
    <p class="text-sm text-gray-600 mt-3">
      Нет аккаунта? <NuxtLink to="/register" class="text-brand">Регистрация</NuxtLink>
    </p>
  </div>
</template>
