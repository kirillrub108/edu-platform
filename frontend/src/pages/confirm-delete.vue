<script setup lang="ts">
import { AlertCircle, CheckCircle2, TriangleAlert } from 'lucide-vue-next'

// Landing page for the deletion link. Like release-email.vue it never
// auto-submits: the click on this page is the destructive step.
const route = useRoute()
const auth = useAuthStore()

const token = computed(() => {
  const raw = route.query.token
  return Array.isArray(raw) ? raw[0] : raw
})

const error = ref<string | null>(null)
const loading = ref(false)
const done = ref(false)

const confirm = async () => {
  if (!token.value) {
    error.value = 'Ссылка недействительна.'
    return
  }
  error.value = null
  loading.value = true
  try {
    await auth.confirmAccountDeletion(token.value)
    done.value = true
  } catch (e: unknown) {
    const err = e as { data?: { detail?: string } }
    error.value =
      err?.data?.detail === 'lessons_in_progress'
        ? 'Идёт генерация урока. Дождитесь её завершения или отмените, затем запросите письмо заново.'
        : 'Ссылка недействительна, устарела или уже использована.'
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
        <div class="mb-3 flex justify-center">
          <AppLogo :with-text="false" size="lg" />
        </div>
        <h1 class="text-xl font-semibold text-gray-900">Удаление аккаунта</h1>
      </div>

      <div class="rounded-2xl border border-gray-100 bg-white p-8 shadow-soft">
        <div v-if="done" class="flex flex-col items-center gap-3 text-center">
          <CheckCircle2 class="h-10 w-10 text-emerald-500" />
          <p class="text-sm text-gray-600">
            Аккаунт удалён. Мы отправили на почту ссылку для восстановления — она действует
            30 дней.
          </p>
          <NuxtLink
            to="/"
            class="inline-block rounded-xl bg-violet-700 px-5 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-violet-600"
          >
            На главную
          </NuxtLink>
        </div>

        <div v-else class="space-y-4">
          <p
            class="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800"
          >
            <TriangleAlert class="mt-0.5 h-4 w-4 shrink-0" />
            <span>
              Аккаунт будет отключён, а все сессии завершены. Данные сохранятся
              <strong>30 дней</strong> — всё это время аккаунт можно вернуть по ссылке из письма.
            </span>
          </p>

          <p
            v-if="error"
            class="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700"
          >
            <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
            <span>{{ error }}</span>
          </p>

          <UiButton
            type="button"
            variant="danger"
            size="lg"
            block
            :loading="loading"
            @click="confirm"
          >
            {{ loading ? 'Удаление…' : 'Подтвердить удаление' }}
          </UiButton>

          <p class="text-center text-sm text-gray-500">
            Передумали?
            <NuxtLink to="/dashboard" class="font-medium text-violet-700 hover:underline">
              Вернуться в кабинет
            </NuxtLink>
          </p>
        </div>
      </div>
    </div>
  </div>
</template>
