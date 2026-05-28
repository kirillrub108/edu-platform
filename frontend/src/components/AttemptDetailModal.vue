<script setup lang="ts">
import { AlertCircle, Check, X } from 'lucide-vue-next'
import type { TeacherQuizAnswer, TeacherQuizAttemptDetail } from '~/types/analytics'

const props = defineProps<{
  lessonId: string
  attemptId: string
}>()

const emit = defineEmits<{ close: [] }>()

const { apiFetch } = useApi()

const detail = ref<TeacherQuizAttemptDetail | null>(null)
const loading = ref(true)
const errMsg = ref('')

const toNum = (v: string | number | null): number | null =>
  v === null || v === '' ? null : Number(v)

const pct = (v: string | number | null): string => {
  const n = toNum(v)
  return n === null ? '—' : `${Math.round(n * 100)}%`
}

const optAt = (payload: Record<string, any>, i: number): string =>
  payload?.options?.[i] ?? `#${i}`

const formatStudentAnswer = (a: TeacherQuizAnswer): string => {
  const p = a.question_payload ?? {}
  const r = a.response ?? {}
  switch (p.type) {
    case 'single_choice':
      return r.selected_index == null ? '—' : optAt(p, r.selected_index)
    case 'multiple_choice': {
      const arr: number[] = r.selected_indices ?? []
      return arr.length ? arr.map(i => optAt(p, i)).join(', ') : '—'
    }
    case 'true_false':
      return r.selected === true ? 'Верно' : r.selected === false ? 'Неверно' : '—'
    case 'short_answer':
    case 'essay':
      return (r.text ?? '').trim() || '—'
    case 'matching': {
      const pairs: [number, number][] = r.pairs ?? []
      return pairs.length
        ? pairs.map(([l, ri]) => `${p.left?.[l] ?? l} → ${p.right?.[ri] ?? ri}`).join('; ')
        : '—'
    }
    case 'ordering': {
      const order: number[] = r.order ?? []
      return order.length ? order.map(i => p.items?.[i] ?? i).join(' → ') : '—'
    }
    case 'fill_blank': {
      const ans: string[] = r.answers ?? []
      return ans.length ? ans.map(x => x || '∅').join(', ') : '—'
    }
    default:
      return '—'
  }
}

const formatCorrectAnswer = (a: TeacherQuizAnswer): string => {
  const p = a.question_payload ?? {}
  switch (p.type) {
    case 'single_choice':
      return optAt(p, p.correct_index)
    case 'multiple_choice':
      return (p.correct_indices ?? []).map((i: number) => optAt(p, i)).join(', ')
    case 'true_false':
      return p.correct ? 'Верно' : 'Неверно'
    case 'short_answer':
      return p.reference_answer ?? '—'
    case 'essay':
      return p.rubric ? `По критериям: ${p.rubric}` : 'Развёрнутый ответ'
    case 'matching':
      return (p.correct_pairs ?? [])
        .map(([l, ri]: [number, number]) => `${p.left?.[l] ?? l} → ${p.right?.[ri] ?? ri}`)
        .join('; ')
    case 'ordering':
      return (p.correct_order ?? []).map((i: number) => p.items?.[i] ?? i).join(' → ')
    case 'fill_blank':
      return (p.blanks ?? []).map((alts: string[]) => (alts ?? []).join(' / ')).join(', ')
    default:
      return '—'
  }
}

const load = async () => {
  loading.value = true
  errMsg.value = ''
  detail.value = null
  try {
    detail.value = await apiFetch<TeacherQuizAttemptDetail>(
      `/lessons/${props.lessonId}/quiz/attempts/${props.attemptId}`,
    )
  } catch (e: any) {
    if (e?.response?.status === 404) {
      errMsg.value = 'Попытка не найдена.'
    } else if (e?.response?.status !== 401) {
      errMsg.value = 'Не удалось загрузить детали попытки.'
    }
  } finally {
    loading.value = false
  }
}

const onKey = (e: KeyboardEvent) => {
  if (e.key === 'Escape') emit('close')
}

watch(() => props.attemptId, load, { immediate: true })

onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-[60] flex items-center justify-center p-4">
      <div class="absolute inset-0 bg-gray-900/40" @click="emit('close')" />

      <div
        class="relative bg-white rounded-2xl border border-gray-100 shadow-xl w-full max-w-3xl max-h-[85vh] flex flex-col overflow-hidden"
      >
        <header class="px-5 py-4 border-b border-gray-100 flex items-center justify-between gap-3">
          <div class="min-w-0">
            <h3 class="text-base font-semibold text-gray-900">Детали попытки</h3>
            <p v-if="detail" class="text-xs text-gray-500 mt-0.5">
              Попытка №{{ detail.attempt_number }} ·
              {{ detail.student_full_name || detail.student_email }}
            </p>
          </div>
          <button
            class="shrink-0 w-8 h-8 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 grid place-items-center transition"
            @click="emit('close')"
          >
            <X class="w-4 h-4" />
          </button>
        </header>

        <div class="flex-1 overflow-y-auto">
          <div v-if="loading" class="p-6 space-y-3">
            <div v-for="i in 4" :key="i" class="h-12 rounded-lg bg-gray-100 animate-pulse" />
          </div>

          <div
            v-else-if="errMsg"
            class="flex items-start gap-3 text-sm text-rose-700 bg-rose-50 border-b border-rose-200 p-4"
          >
            <AlertCircle class="w-5 h-5 shrink-0 mt-0.5" />
            <div>{{ errMsg }}</div>
          </div>

          <table v-else-if="detail" class="w-full text-sm">
            <thead class="bg-gray-50 text-gray-500 sticky top-0">
              <tr>
                <th class="px-3 py-2.5 text-left font-medium w-8">#</th>
                <th class="px-3 py-2.5 text-left font-medium">Вопрос</th>
                <th class="px-3 py-2.5 text-left font-medium">Ответ студента</th>
                <th class="px-3 py-2.5 text-left font-medium">Правильный ответ</th>
                <th class="px-3 py-2.5 text-center font-medium w-12" />
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-50">
              <tr v-for="(a, idx) in detail.answers" :key="a.id" class="align-top">
                <td class="px-3 py-3 text-gray-400 tabular-nums">{{ idx + 1 }}</td>
                <td class="px-3 py-3 text-gray-900">{{ a.question_payload?.prompt ?? '—' }}</td>
                <td class="px-3 py-3 text-gray-700">{{ formatStudentAnswer(a) }}</td>
                <td class="px-3 py-3 text-gray-700">{{ formatCorrectAnswer(a) }}</td>
                <td class="px-3 py-3 text-center">
                  <Check v-if="a.is_correct === true" class="w-4 h-4 mx-auto text-emerald-600" />
                  <X v-else-if="a.is_correct === false" class="w-4 h-4 mx-auto text-rose-500" />
                  <span v-else class="text-xs text-amber-600">проверка…</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <footer
          v-if="detail"
          class="px-5 py-3 border-t border-gray-100 flex items-center justify-between gap-3 bg-gray-50"
        >
          <span class="text-sm text-gray-500">Итоговый балл</span>
          <span class="flex items-center gap-2">
            <span
              class="text-base font-semibold tabular-nums"
              :class="detail.passed ? 'text-emerald-600' : 'text-rose-600'"
            >{{ pct(detail.score) }}</span>
            <span
              v-if="detail.passed"
              class="text-xs bg-emerald-100 text-emerald-700 px-2 py-0.5 rounded-full"
            >пройден</span>
            <span
              v-else-if="detail.status === 'graded'"
              class="text-xs bg-rose-100 text-rose-700 px-2 py-0.5 rounded-full"
            >не сдан</span>
            <span
              v-else
              class="text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full"
            >на проверке</span>
          </span>
        </footer>
      </div>
    </div>
  </Teleport>
</template>
