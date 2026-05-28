<script setup lang="ts">
import { AlertCircle, ChevronRight, Inbox, X } from 'lucide-vue-next'
import type { TeacherQuizAttempt } from '~/types/analytics'

const props = defineProps<{
  lessonId: string
  student: { id: string; name: string; email: string }
}>()

const emit = defineEmits<{ close: [] }>()

const { apiFetch } = useApi()

const attempts = ref<TeacherQuizAttempt[]>([])
const loading = ref(true)
const errMsg = ref('')
const selectedAttemptId = ref<string | null>(null)
// True when the student has a single attempt and we skipped the list — closing
// the detail then closes the whole panel rather than returning to a 1-row list.
const collapsedSingle = ref(false)

const toNum = (v: string | number | null): number | null =>
  v === null || v === '' ? null : Number(v)

const pct = (v: string | number | null): string => {
  const n = toNum(v)
  return n === null ? '—' : `${Math.round(n * 100)}%`
}

const fmtDate = (s: string | null): string => {
  if (!s) return '—'
  return new Date(s).toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

const statusBadge = (a: TeacherQuizAttempt): { label: string; cls: string } => {
  if (a.passed === true) return { label: 'сдал', cls: 'bg-emerald-100 text-emerald-700' }
  if (a.status === 'graded') return { label: 'не сдал', cls: 'bg-rose-100 text-rose-700' }
  return { label: 'на проверке', cls: 'bg-amber-100 text-amber-700' }
}

const load = async () => {
  loading.value = true
  errMsg.value = ''
  try {
    const all = await apiFetch<TeacherQuizAttempt[]>(
      `/lessons/${props.lessonId}/quiz/attempts`,
    )
    attempts.value = all
      .filter(a => a.student_id === props.student.id)
      .sort((x, y) => x.attempt_number - y.attempt_number)
    // Single attempt → collapse straight into the detail view.
    if (attempts.value.length === 1) {
      collapsedSingle.value = true
      selectedAttemptId.value = attempts.value[0].id
    }
  } catch (e: any) {
    if (e?.response?.status === 404) {
      errMsg.value = 'Тест для этого урока недоступен.'
    } else if (e?.response?.status !== 401) {
      errMsg.value = 'Не удалось загрузить попытки.'
    }
  } finally {
    loading.value = false
  }
}

const onDetailClose = () => {
  selectedAttemptId.value = null
  if (collapsedSingle.value) emit('close')
}

const onKey = (e: KeyboardEvent) => {
  // Let the detail modal own Escape while it's open.
  if (e.key === 'Escape' && !selectedAttemptId.value) emit('close')
}

onMounted(() => {
  load()
  window.addEventListener('keydown', onKey)
})
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-50 flex justify-end">
      <div class="absolute inset-0 bg-gray-900/40" @click="emit('close')" />

      <aside
        class="relative bg-gray-50 w-full max-w-md h-full shadow-xl flex flex-col overflow-hidden"
      >
        <header class="px-5 py-4 bg-white border-b border-gray-100 flex items-center justify-between gap-3">
          <div class="min-w-0">
            <h3 class="text-base font-semibold text-gray-900 truncate">
              {{ student.name }}
            </h3>
            <p class="text-xs text-gray-500 truncate">{{ student.email }}</p>
          </div>
          <button
            class="shrink-0 w-8 h-8 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 grid place-items-center transition"
            @click="emit('close')"
          >
            <X class="w-4 h-4" />
          </button>
        </header>

        <div class="flex-1 overflow-y-auto p-5">
          <h4 class="text-xs uppercase tracking-wide text-gray-400 mb-3">Попытки</h4>

          <div v-if="loading" class="space-y-3">
            <div v-for="i in 3" :key="i" class="h-16 rounded-xl bg-gray-200/60 animate-pulse" />
          </div>

          <div
            v-else-if="errMsg"
            class="flex items-start gap-3 text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-xl p-4"
          >
            <AlertCircle class="w-5 h-5 shrink-0 mt-0.5" />
            <div>{{ errMsg }}</div>
          </div>

          <div
            v-else-if="attempts.length === 0"
            class="text-center text-gray-500 py-12"
          >
            <Inbox class="w-10 h-10 mx-auto mb-3 text-gray-300" />
            <p class="text-sm">Нет данных о попытках</p>
          </div>

          <ul v-else class="space-y-2">
            <li
              v-for="a in attempts"
              :key="a.id"
              class="bg-white border border-gray-100 rounded-xl p-3 flex items-center gap-3 cursor-pointer hover:border-violet-300 hover:bg-violet-50/30 transition"
              @click="selectedAttemptId = a.id"
            >
              <div class="min-w-0 flex-1">
                <div class="text-sm font-medium text-gray-900">Попытка №{{ a.attempt_number }}</div>
                <div class="text-xs text-gray-500 tabular-nums">{{ fmtDate(a.submitted_at ?? a.graded_at) }}</div>
              </div>
              <div
                class="text-sm font-semibold tabular-nums"
                :class="a.passed ? 'text-emerald-600' : 'text-rose-600'"
              >{{ pct(a.score) }}</div>
              <span
                class="text-xs px-2 py-0.5 rounded-full"
                :class="statusBadge(a).cls"
              >{{ statusBadge(a).label }}</span>
              <ChevronRight class="w-4 h-4 text-gray-300" />
            </li>
          </ul>
        </div>
      </aside>
    </div>
  </Teleport>

  <AttemptDetailModal
    v-if="selectedAttemptId"
    :lesson-id="lessonId"
    :attempt-id="selectedAttemptId"
    @close="onDetailClose"
  />
</template>
