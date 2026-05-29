<script setup lang="ts">
import { GraduationCap, AlertCircle } from 'lucide-vue-next'

const auth = useAuthStore()
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
    await auth.register(email.value, password.value, role.value, fullName.value || undefined)
    await navigateTo(role.value === 'teacher' ? '/dashboard' : '/student/dashboard')
  } catch (e: any) {
    error.value = e?.data?.detail ?? 'Ошибка регистрации'
  } finally {
    loading.value = false
  }
}

onMounted(restoreScroll)
</script>

<template>
  <div class="px-6 py-12 sm:py-16 flex justify-center">
    <div class="w-full max-w-sm">
      <div class="mb-6 text-center">
        <div class="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-gradient-to-br from-violet-600 to-purple-500 shadow-sm">
          <GraduationCap class="h-6 w-6 text-white" />
        </div>
        <h1 class="text-xl font-semibold text-gray-900">Создать аккаунт</h1>
        <p class="mt-1 text-sm text-gray-500">Начните создавать видеолекции бесплатно</p>
      </div>

      <div class="rounded-2xl border border-gray-100 bg-white p-8 shadow-soft">
        <!-- Role toggle -->
        <div class="mb-2 flex overflow-hidden rounded-xl border border-gray-200">
          <button
            type="button"
            class="flex-1 py-2 text-sm font-medium transition-colors"
            :class="role === 'teacher' ? 'bg-violet-700 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'"
            @click="role = 'teacher'"
          >
            Преподаватель
          </button>
          <button
            type="button"
            class="flex-1 py-2 text-sm font-medium transition-colors"
            :class="role === 'student' ? 'bg-violet-700 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'"
            @click="role = 'student'"
          >
            Ученик
          </button>
        </div>
        <p class="mb-5 text-center text-xs text-gray-400">
          <template v-if="role === 'teacher'">Создаёте и публикуете курсы</template>
          <template v-else>Проходите курсы по ссылке от учителя</template>
        </p>

        <form class="space-y-4" @submit.prevent="submit">
          <UiInput v-model="fullName" label="Имя" placeholder="Необязательно" />
          <UiInput
            v-model="email"
            label="Email"
            type="email"
            placeholder="you@example.com"
            autocomplete="email"
          />
          <UiInput
            v-model="password"
            label="Пароль"
            type="password"
            placeholder="••••••••"
            autocomplete="new-password"
            hint="Минимум 8 символов"
          />

          <p
            v-if="error"
            class="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700"
          >
            <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
            <span>{{ error }}</span>
          </p>

          <UiButton type="submit" variant="primary" size="lg" block :loading="loading">
            {{ loading ? 'Создание…' : 'Зарегистрироваться' }}
          </UiButton>
        </form>
      </div>

      <p class="mt-5 text-center text-sm text-gray-500">
        Уже есть аккаунт?
        <NuxtLink to="/login" class="font-medium text-violet-700 hover:underline">Войти</NuxtLink>
      </p>
    </div>
  </div>
</template>
