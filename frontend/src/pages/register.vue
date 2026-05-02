<script setup lang="ts">
const { register } = useAuth()
const email = ref('')
const password = ref('')
const fullName = ref('')
const error = ref<string | null>(null)
const loading = ref(false)

const submit = async () => {
  error.value = null
  loading.value = true
  try {
    await register(email.value, password.value, fullName.value || undefined)
    await navigateTo('/dashboard')
  } catch (e: any) {
    error.value = e?.data?.detail ?? 'Registration failed'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="max-w-sm mx-auto bg-white p-6 rounded-lg border border-gray-200">
    <h1 class="text-xl font-semibold mb-4">Регистрация</h1>
    <form class="space-y-3" @submit.prevent="submit">
      <input v-model="fullName" type="text" placeholder="Имя" class="w-full border rounded px-3 py-2" />
      <input v-model="email" type="email" placeholder="Email" required class="w-full border rounded px-3 py-2" />
      <input v-model="password" type="password" placeholder="Пароль (мин. 6)" required minlength="6" class="w-full border rounded px-3 py-2" />
      <button :disabled="loading" class="w-full bg-brand text-white rounded py-2">
        {{ loading ? '...' : 'Создать аккаунт' }}
      </button>
      <p v-if="error" class="text-sm text-red-600">{{ error }}</p>
    </form>
  </div>
</template>
