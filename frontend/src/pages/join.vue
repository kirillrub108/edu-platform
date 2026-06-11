<script setup lang="ts">
// Public page — no auth middleware. Auth state is resolved manually on mount.

const route = useRoute()
const { apiFetch } = useApi()
const auth = useAuthStore()

interface CoursePreview {
  id: string
  title: string
  description: string | null
  access_mode: string
  is_published: boolean
}

const preview = ref<CoursePreview | null>(null)
const loading = ref(true)
const pageError = ref('')
const isEnrolled = ref(false)
const enrolling = ref(false)
const enrollError = ref('')

const code = computed(() => route.query.code as string | undefined)
const courseId = computed(() => route.query.courseId as string | undefined)
const loginUrl = computed(() => `/login?redirect=${encodeURIComponent(route.fullPath)}`)

onMounted(async () => {
  // Resolve auth state before deciding which UI to show.
  if (!auth.user) {
    await auth.fetchMe()
  }

  if (!code.value && !courseId.value) {
    pageError.value = 'Недействительная ссылка'
    loading.value = false
    return
  }

  try {
    const params: Record<string, string> = {}
    if (code.value) params.code = code.value
    else if (courseId.value) params.course_id = courseId.value

    preview.value = await apiFetch<CoursePreview>('/students/courses/preview', { query: params })

    // Check if already enrolled (requires auth).
    if (auth.isAuthenticated && preview.value) {
      try {
        await apiFetch(`/students/courses/${preview.value.id}`)
        isEnrolled.value = true
      } catch {
        isEnrolled.value = false
      }
    }
  } catch (e: any) {
    pageError.value =
      e?.response?.status === 404
        ? 'Код недействителен или курс недоступен'
        : 'Не удалось загрузить информацию о курсе'
  } finally {
    loading.value = false
  }
})

const enroll = async () => {
  if (!preview.value) return
  enrolling.value = true
  enrollError.value = ''
  try {
    const body: Record<string, string> = code.value
      ? { access_code: code.value }
      : { course_id: preview.value.id }
    const result = await apiFetch<{ enrollment_id: string; course_id: string }>(
      '/students/enroll',
      { method: 'POST', body }
    )
    await navigateTo(`/student/courses/${result.course_id}`)
  } catch (e: any) {
    enrollError.value = e?.data?.detail ?? 'Ошибка при записи на курс'
  } finally {
    enrolling.value = false
  }
}
</script>

<template>
  <div class="min-h-[80vh] flex items-center justify-center px-4">
    <div class="w-full max-w-md">

      <div v-if="loading" class="text-center text-gray-500 py-16">Загрузка…</div>

      <div v-else-if="pageError" class="bg-red-50 border border-red-200 rounded-xl p-8 text-center">
        <p class="text-red-600 font-medium mb-4">{{ pageError }}</p>
        <NuxtLink to="/" class="text-sm text-brand hover:underline">На главную</NuxtLink>
      </div>

      <div v-else-if="preview" class="bg-white rounded-xl border shadow-sm p-8">
        <p class="text-xs text-gray-500 uppercase tracking-wide mb-1">Приглашение на курс</p>
        <h1 class="text-xl font-semibold text-gray-900 mb-2">{{ preview.title }}</h1>
        <p v-if="preview.description" class="text-sm text-gray-500 mb-8">{{ preview.description }}</p>
        <div v-else class="mb-8" />

        <!-- Already enrolled -->
        <template v-if="isEnrolled">
          <p class="text-sm text-green-700 bg-green-50 border border-green-200 rounded-lg px-4 py-3 mb-4">
            Вы уже записаны на этот курс.
          </p>
          <NuxtLink
            :to="`/student/courses/${preview.id}`"
            class="block w-full text-center px-4 py-2.5 bg-brand text-white rounded-lg text-sm font-medium hover:opacity-90 transition"
          >
            Перейти к курсу →
          </NuxtLink>
        </template>

        <!-- Authenticated, not enrolled -->
        <template v-else-if="auth.isAuthenticated">
          <p v-if="enrollError" class="text-sm text-red-600 mb-3">{{ enrollError }}</p>
          <button
            class="w-full px-4 py-2.5 bg-brand text-white rounded-lg text-sm font-medium disabled:opacity-50 hover:opacity-90 transition"
            :disabled="enrolling"
            @click="enroll"
          >
            {{ enrolling ? '…' : 'Записаться на курс' }}
          </button>
        </template>

        <!-- Not authenticated -->
        <template v-else>
          <p class="text-sm text-gray-500 mb-4">Войдите в аккаунт, чтобы записаться на курс.</p>
          <NuxtLink
            :to="loginUrl"
            class="block w-full text-center px-4 py-2.5 bg-brand text-white rounded-lg text-sm font-medium hover:opacity-90 transition"
          >
            Войти
          </NuxtLink>
          <p class="text-center text-sm text-gray-500 mt-3">
            Нет аккаунта?
            <NuxtLink to="/register" class="text-brand hover:underline">Зарегистрироваться</NuxtLink>
          </p>
        </template>
      </div>

    </div>
  </div>
</template>
