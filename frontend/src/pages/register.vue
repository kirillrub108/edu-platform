<script setup lang="ts">
const { register } = useAuth()
const email = ref('')
const password = ref('')
const fullName = ref('')
const role = ref<'teacher' | 'student'>('teacher')
const error = ref<string | null>(null)
const loading = ref(false)

const submit = async () => {
  error.value = null
  loading.value = true
  try {
    await register(email.value, password.value, role.value, fullName.value || undefined)
    await navigateTo(role.value === 'teacher' ? '/dashboard' : '/student/dashboard')
  } catch (e: any) {
    error.value = e?.data?.detail ?? 'Ошибка регистрации'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="max-w-sm mx-auto">
    <div class="bg-white p-8 rounded-xl border border-gray-200 shadow-sm">
      <h1 class="text-xl font-semibold mb-6 text-center">Создать аккаунт</h1>

      <!-- Role toggle -->
      <div class="flex rounded-lg border border-gray-200 overflow-hidden mb-5">
        <button
          type="button"
          class="flex-1 py-2 text-sm font-medium transition"
          :class="role === 'teacher' ? 'bg-brand text-white' : 'bg-white text-gray-600 hover:bg-gray-50'"
          @click="role = 'teacher'"
        >
          Преподаватель
        </button>
        <button
          type="button"
          class="flex-1 py-2 text-sm font-medium transition"
          :class="role === 'student' ? 'bg-brand text-white' : 'bg-white text-gray-600 hover:bg-gray-50'"
          @click="role = 'student'"
        >
          Студент
        </button>
      </div>

      <p class="text-xs text-gray-400 text-center mb-5 -mt-2">
        <template v-if="role === 'teacher'">Создаёте и публикуете курсы</template>
        <template v-else>Проходите курсы по ссылке от учителя</template>
      </p>

      <form class="space-y-3" @submit.prevent="submit">
        <input
          v-model="fullName"
          type="text"
          placeholder="Имя (необязательно)"
          class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
        />
        <input
          v-model="email"
          type="email"
          placeholder="Email"
          required
          class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
        />
        <input
          v-model="password"
          type="password"
          placeholder="Пароль (минимум 8 символов)"
          required
          minlength="8"
          class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
        />

        <p v-if="error" class="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">
          {{ error }}
        </p>

        <button
          type="submit"
          :disabled="loading"
          class="w-full bg-brand text-white rounded-lg py-2 font-medium disabled:opacity-50 transition"
        >
          {{ loading ? 'Создание…' : 'Зарегистрироваться' }}
        </button>
      </form>

      <p class="text-center text-sm text-gray-500 mt-4">
        Уже есть аккаунт?
        <NuxtLink to="/login" class="text-brand hover:underline">Войти</NuxtLink>
      </p>
    </div>
  </div>
</template>
