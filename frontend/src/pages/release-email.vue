<script setup lang="ts">
import { AlertCircle, CheckCircle2, TriangleAlert } from 'lucide-vue-next'

// Landing page for the "free my address" link. Deliberately NOT auto-submitting
// like restore-account does: this one is irreversible, so it takes a click.
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
    await auth.confirmEmailRelease(token.value)
    done.value = true
  } catch {
    error.value = 'Ссылка устарела или уже использована.'
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
        <h1 class="text-xl font-semibold text-gray-900">Освобождение адреса</h1>
      </div>

      <div class="rounded-2xl border border-gray-100 bg-white p-8 shadow-soft">
        <div v-if="done" class="flex flex-col items-center gap-3 text-center">
          <CheckCircle2 class="h-10 w-10 text-emerald-500" />
          <p class="text-sm text-gray-600">
            Адрес освобождён. Теперь на него можно зарегистрировать новый аккаунт.
          </p>
          <NuxtLink
            to="/register"
            class="inline-block rounded-xl bg-violet-700 px-5 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-violet-600"
          >
            Зарегистрироваться
          </NuxtLink>
        </div>

        <div v-else class="space-y-4">
          <p
            class="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800"
          >
            <TriangleAlert class="mt-0.5 h-4 w-4 shrink-0" />
            <span>
              Данные старого аккаунта будут обезличены безвозвратно.
              <strong>Восстановить его после этого будет невозможно.</strong>
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
            {{ loading ? 'Освобождение…' : 'Освободить адрес' }}
          </UiButton>

          <p class="text-center text-sm text-gray-500">
            Передумали?
            <NuxtLink to="/restore-account" class="font-medium text-violet-700 hover:underline">
              Восстановить аккаунт
            </NuxtLink>
          </p>
        </div>
      </div>
    </div>
  </div>
</template>
