<script setup lang="ts">
/**
 * Student-side quiz player. Three states:
 *
 *   1. Lobby — quiz available, no in-progress attempt → "Start" button.
 *   2. Active — questions visible, autosave on each change, "Submit" at end.
 *   3. Result — score + per-question outcome. If show_answers && attempts=1,
 *      correct answers are shown alongside the student's response.
 *
 * The composable owns all server I/O — this component is pure presentation.
 */
import { Sparkles } from 'lucide-vue-next'
import type { StudentQuestion, AnswerResult } from '~/composables/useQuizAttempt'

interface AttemptRow {
  id: string
  attempt_number: number
  score: number | null
  passed: boolean | null
  attempted_at: string
  status: string
}

interface AttemptsData {
  attempts: AttemptRow[]
  best_score: number | null
  final_score: number | null
  is_manual: boolean
  is_passed: boolean
}

const props = defineProps<{
  lessonId: string
  // Teacher «view as student» dry-run: owner endpoints + client-side grading,
  // nothing is written to the backend (no attempts, no LLM grading).
  preview?: boolean
}>()

const emit = defineEmits<{
  // Fires once after fetchInfo resolves; value = whether a quiz exists for this lesson
  'has-quiz': [value: boolean]
  // Fires when the graded result comes back with passed === true
  'quiz-passed': []
}>()

const lessonIdRef = computed(() => props.lessonId)

// `preview` is fixed for the component's lifetime (set by the page), so the
// conditional composable call is stable across re-renders.
const previewAttempt = props.preview ? useQuizPreview(lessonIdRef) : null
const {
  info, attemptId, questions, responses, result,
  loading, submitting, error, hasQuiz, saveStatus, gradingPending,
  fetchInfo, start, setResponse, submit, reset,
} = previewAttempt ?? useQuizAttempt(lessonIdRef)

const quizStatus = previewAttempt?.quizStatus ?? ref<'draft' | 'published' | null>(null)
const previewDraftQuiz = computed(
  () => props.preview && hasQuiz.value && quizStatus.value !== 'published',
)

const { apiFetch } = useApi()
const attemptsData = ref<AttemptsData | null>(null)
const attemptsLoading = ref(false)

const loadAttempts = async () => {
  if (props.preview) return // dry-run: no attempts exist, endpoint is student-only
  if (!hasQuiz.value) return
  attemptsLoading.value = true
  try {
    attemptsData.value = await apiFetch<AttemptsData>(
      `/students/lessons/${props.lessonId}/quiz-attempts`,
    )
  } catch { /* ignore — no attempts or quiz not available */ } finally {
    attemptsLoading.value = false
  }
}

const fmtDate = (iso: string) =>
  new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })

const allAnswered = computed(() => {
  if (!questions.value.length) return false
  return questions.value.every(q => q.id in responses.value)
})

const remaining = computed(() => {
  if (!info.value) return null
  if (info.value.attempts_allowed === null) return null
  return Math.max(0, info.value.attempts_allowed - info.value.attempts_used)
})

watch(lessonIdRef, async (id, prev) => {
  if (id === prev) return
  attemptsData.value = null
  reset()
  await fetchInfo()
  await loadAttempts()
})

onMounted(async () => {
  await fetchInfo()
  emit('has-quiz', hasQuiz.value)
  await loadAttempts()
})

// Reload attempts whenever a graded result becomes available.
watch(
  () => result.value?.status,
  async (status) => {
    if (status === 'graded') await loadAttempts()
  },
)

// Emit quiz-passed whenever result transitions to graded + passed.
// immediate:true covers the case where the student revisits an already-passed lesson.
watch(result, (r) => {
  if (r?.status === 'graded' && r.passed === true) {
    emit('quiz-passed')
  }
}, { immediate: true })

const answerFor = (qid: string): AnswerResult | undefined =>
  result.value?.answers.find(a => a.question_id === qid)

// ── per-type response helpers ────────────────────────────────────────────

const singleChoiceSelected = (qid: string) => responses.value[qid]?.selected_index
const setSingleChoice = (qid: string, idx: number) =>
  setResponse(qid, { selected_index: idx })

const mcSelected = (qid: string): number[] => responses.value[qid]?.selected_indices ?? []
const toggleMc = (qid: string, idx: number) => {
  const current = new Set<number>(mcSelected(qid))
  if (current.has(idx)) current.delete(idx)
  else current.add(idx)
  setResponse(qid, { selected_indices: Array.from(current).sort((a, b) => a - b) })
}

const tfSelected = (qid: string) => responses.value[qid]?.selected
const setTf = (qid: string, val: boolean) => setResponse(qid, { selected: val })

const textValue = (qid: string) => responses.value[qid]?.text ?? ''
const setText = (qid: string, val: string) => setResponse(qid, { text: val })

const orderingItems = (q: StudentQuestion) => {
  // The user's current order; defaults to original list.
  const order: number[] = responses.value[q.id]?.order ?? q.payload.items.map((_: any, i: number) => i)
  return order.map((i: number) => ({ idx: i, text: q.payload.items[i] }))
}
const moveOrdering = (q: StudentQuestion, idx: number, dir: -1 | 1) => {
  const list = [...(responses.value[q.id]?.order ?? q.payload.items.map((_: any, i: number) => i))]
  const target = idx + dir
  if (target < 0 || target >= list.length) return
  const tmp = list[idx]; list[idx] = list[target]; list[target] = tmp
  setResponse(q.id, { order: list })
}

const matchingValue = (q: StudentQuestion, leftIdx: number): number | null => {
  const pairs: [number, number][] = responses.value[q.id]?.pairs ?? []
  const found = pairs.find(([li]) => li === leftIdx)
  return found ? found[1] : null
}
const setMatching = (q: StudentQuestion, leftIdx: number, rightIdx: number) => {
  const pairs: [number, number][] = (responses.value[q.id]?.pairs ?? []).filter(
    ([li]: [number, number]) => li !== leftIdx,
  )
  if (rightIdx >= 0) pairs.push([leftIdx, rightIdx])
  setResponse(q.id, { pairs })
}

const blanksValue = (q: StudentQuestion, idx: number) => responses.value[q.id]?.answers?.[idx] ?? ''
const setBlank = (q: StudentQuestion, idx: number, val: string) => {
  const arr: string[] = [...(responses.value[q.id]?.answers ?? [])]
  while (arr.length < q.payload.blanks_count) arr.push('')
  arr[idx] = val
  setResponse(q.id, { answers: arr })
}
</script>

<template>
  <section class="bg-white rounded-2xl border border-gray-100 shadow-soft p-5 space-y-4">
    <header class="flex items-center justify-between gap-3 flex-wrap">
      <h2 class="text-lg font-semibold text-gray-900 flex items-center gap-2">
        Тест
        <span
          v-if="previewDraftQuiz"
          class="text-xs px-2 py-0.5 rounded-full font-medium bg-amber-100 text-amber-700"
        >Студент не увидит</span>
      </h2>
      <div v-if="info" class="text-xs text-gray-500">
        Попыток: {{ info.attempts_used }}<template v-if="info.attempts_allowed !== null"> / {{ info.attempts_allowed }}</template>
        <span class="ml-2">Порог: {{ Math.round(Number(info.pass_threshold) * 100) }}%</span>
      </div>
    </header>

    <div v-if="loading" class="text-sm text-gray-500">Загрузка…</div>

    <div
      v-else-if="!hasQuiz"
      class="text-sm text-gray-500 bg-violet-50/40 border border-violet-100 rounded-2xl p-6 text-center"
    >Тест для этого урока ещё не опубликован.</div>

    <div
      v-else-if="error"
      class="text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-xl px-3 py-2"
    >{{ error }}</div>

    <!-- Result view -->
    <template v-else-if="result">
      <div class="flex items-center gap-3 flex-wrap">
        <span
          v-if="result.status === 'graded'"
          class="text-xl font-semibold"
          :class="result.passed === null ? 'text-gray-600' : result.passed ? 'text-green-600' : 'text-red-600'"
        >
          {{ result.passed === null ? 'Ответы проверены' : result.passed ? 'Тест пройден' : 'Тест не пройден' }}
        </span>
        <span
          v-else-if="result.status === 'submitted'"
          class="text-base font-medium text-violet-700"
        >Проверяется…</span>
        <span v-if="result.score !== null" class="text-gray-500 text-sm">
          {{ Math.round(Number(result.score) * 100) }}%
        </span>
        <span
          v-if="gradingPending"
          class="text-xs text-gray-500"
        >ИИ оценивает развёрнутые ответы…</span>
        <span
          v-if="result.ai_graded"
          class="inline-flex items-center gap-1 text-xs bg-violet-100 text-violet-700 px-2 py-0.5 rounded-full"
          title="Развёрнутые ответы проверены ИИ"
        >
          <Sparkles class="w-3 h-3" />
          Проверено ИИ
        </span>
      </div>

      <div class="space-y-3">
        <div
          v-for="q in result.questions"
          :key="q.id"
          class="rounded-lg border p-3"
          :class="answerFor(q.id)?.is_correct === true
            ? 'border-green-200 bg-green-50'
            : answerFor(q.id)?.is_correct === false
              ? 'border-red-200 bg-red-50'
              : 'border-gray-200 bg-gray-50'"
        >
          <p class="text-sm font-medium mb-2">{{ q.payload.prompt ?? '' }}</p>

          <div v-if="answerFor(q.id)?.needs_review" class="text-xs text-amber-600 mb-1">
            Ожидает ручной проверки преподавателем.
          </div>

          <!-- show_answers && attempts==1: render the snapshot's correct payload -->
          <div
            v-if="answerFor(q.id)?.correct_payload"
            class="text-xs text-gray-600 mt-2 pl-2 border-l-2 border-violet-200"
          >
            <template v-if="q.type === 'single_choice'">
              Правильный ответ: <b>{{ answerFor(q.id)!.correct_payload!.options[answerFor(q.id)!.correct_payload!.correct_index] }}</b>
            </template>
            <template v-else-if="q.type === 'multiple_choice'">
              Правильные: <b>{{ answerFor(q.id)!.correct_payload!.correct_indices.map((i: number) => answerFor(q.id)!.correct_payload!.options[i]).join(', ') }}</b>
            </template>
            <template v-else-if="q.type === 'true_false'">
              Правильно: <b>{{ answerFor(q.id)!.correct_payload!.correct ? 'Верно' : 'Неверно' }}</b>
            </template>
            <template v-else-if="q.type === 'short_answer'">
              Эталон: <b>{{ answerFor(q.id)!.correct_payload!.reference_answer }}</b>
              <template v-if="preview && answerFor(q.id)!.correct_payload!.rubric">
                <br />Критерии: {{ answerFor(q.id)!.correct_payload!.rubric }}
              </template>
            </template>
            <template v-else-if="q.type === 'essay'">
              Критерии: <b>{{ answerFor(q.id)!.correct_payload!.rubric }}</b>
            </template>
          </div>

          <div
            v-if="answerFor(q.id)?.llm_feedback"
            class="text-xs text-gray-700 mt-2"
          >{{ answerFor(q.id)!.llm_feedback }}</div>
        </div>
      </div>
    </template>

    <!-- Active attempt -->
    <template v-else-if="attemptId && questions.length > 0">
      <div class="text-xs text-gray-500">
        <span v-if="saveStatus === 'saving'">сохраняется…</span>
        <span v-else-if="saveStatus === 'saved'">сохранено</span>
        <span v-else-if="saveStatus === 'error'" class="text-rose-500">ошибка автосохранения</span>
      </div>

      <ol class="space-y-4">
        <li
          v-for="q in questions"
          :key="q.id"
          class="rounded-lg border border-gray-200 p-3 space-y-2"
        >
          <p class="text-sm font-medium">{{ q.payload.prompt }}</p>

          <template v-if="q.type === 'single_choice'">
            <label
              v-for="(opt, oi) in q.payload.options"
              :key="oi"
              class="flex items-center gap-2 text-sm"
            >
              <input
                type="radio"
                :name="`q-${q.id}`"
                :checked="singleChoiceSelected(q.id) === oi"
                @change="() => setSingleChoice(q.id, oi)"
              />
              {{ opt }}
            </label>
          </template>

          <template v-else-if="q.type === 'multiple_choice'">
            <label
              v-for="(opt, oi) in q.payload.options"
              :key="oi"
              class="flex items-center gap-2 text-sm"
            >
              <input
                type="checkbox"
                :checked="mcSelected(q.id).includes(oi)"
                @change="() => toggleMc(q.id, oi)"
              />
              {{ opt }}
            </label>
          </template>

          <template v-else-if="q.type === 'true_false'">
            <div class="flex gap-3 text-sm">
              <label class="flex items-center gap-1">
                <input type="radio" :name="`q-${q.id}`" :checked="tfSelected(q.id) === true" @change="() => setTf(q.id, true)" /> Верно
              </label>
              <label class="flex items-center gap-1">
                <input type="radio" :name="`q-${q.id}`" :checked="tfSelected(q.id) === false" @change="() => setTf(q.id, false)" /> Неверно
              </label>
            </div>
          </template>

          <template v-else-if="q.type === 'short_answer'">
            <input
              :value="textValue(q.id)"
              class="w-full rounded-lg border border-gray-200 px-2 py-1 text-sm"
              @input="(e: any) => setText(q.id, e.target.value)"
            />
          </template>

          <template v-else-if="q.type === 'essay'">
            <textarea
              :value="textValue(q.id)"
              rows="4"
              class="w-full rounded-lg border border-gray-200 px-2 py-1 text-sm"
              @input="(e: any) => setText(q.id, e.target.value)"
            />
          </template>

          <template v-else-if="q.type === 'matching'">
            <div
              v-for="(left, li) in q.payload.left"
              :key="li"
              class="flex items-center gap-2 text-sm"
            >
              <span class="flex-1">{{ left }}</span>
              <span class="text-gray-400">→</span>
              <select
                class="rounded-lg border border-gray-200 px-2 py-1"
                :value="matchingValue(q, li) ?? ''"
                @change="(e: any) => setMatching(q, li, e.target.value === '' ? -1 : Number(e.target.value))"
              >
                <option value="">—</option>
                <option v-for="(right, ri) in q.payload.right" :key="ri" :value="ri">{{ right }}</option>
              </select>
            </div>
          </template>

          <template v-else-if="q.type === 'ordering'">
            <div
              v-for="(item, i) in orderingItems(q)"
              :key="`${q.id}-${item.idx}`"
              class="flex items-center gap-2 text-sm"
            >
              <span class="text-xs text-gray-500 w-4">{{ i + 1 }}.</span>
              <span class="flex-1">{{ item.text }}</span>
              <button type="button" class="text-xs" :disabled="i === 0" @click="moveOrdering(q, i, -1)">↑</button>
              <button type="button" class="text-xs" :disabled="i === q.payload.items.length - 1" @click="moveOrdering(q, i, 1)">↓</button>
            </div>
          </template>

          <template v-else-if="q.type === 'fill_blank'">
            <p class="text-sm text-gray-700 whitespace-pre-wrap">{{ q.payload.prompt }}</p>
            <div
              v-for="i in q.payload.blanks_count"
              :key="i"
              class="flex items-center gap-2 text-sm"
            >
              <span class="text-xs text-gray-500 w-6">{{ i }}.</span>
              <input
                :value="blanksValue(q, i - 1)"
                class="flex-1 rounded-lg border border-gray-200 px-2 py-1"
                @input="(e: any) => setBlank(q, i - 1, e.target.value)"
              />
            </div>
          </template>
        </li>
      </ol>

      <div class="flex items-center gap-3">
        <button
          type="button"
          class="px-4 py-2 bg-violet-600 text-white rounded-lg text-sm disabled:opacity-50"
          :disabled="submitting"
          @click="submit"
        >
          {{ submitting ? '…' : preview ? 'Проверить' : 'Отправить ответы' }}
        </button>
        <span v-if="!allAnswered" class="text-xs text-gray-500">
          Можно отправить и без всех ответов — пустые засчитаются как неверные.
        </span>
      </div>
    </template>

    <!-- Lobby -->
    <template v-else-if="info">
      <div class="text-sm text-gray-600">
        <p v-if="preview">
          Пробное прохождение — результат нигде не сохранится.
        </p>
        <p v-else-if="remaining !== null && remaining === 0" class="text-rose-600">
          Лимит попыток исчерпан.
        </p>
        <p v-else>
          У вас <template v-if="remaining !== null">{{ remaining }} попыток</template>
          <template v-else>неограниченное количество попыток</template>.
        </p>
      </div>
      <button
        type="button"
        class="px-4 py-2 bg-violet-600 text-white rounded-lg text-sm"
        :disabled="!preview && remaining === 0"
        @click="start"
      >Начать тест</button>
    </template>
  </section>

  <!-- Мои попытки -->
  <section
    v-if="attemptsData && attemptsData.attempts.length > 0"
    class="bg-white rounded-2xl border border-gray-100 shadow-soft p-5 space-y-4"
  >
    <div class="flex items-center justify-between gap-3 flex-wrap">
      <h3 class="text-base font-semibold text-gray-900">Мои попытки</h3>
      <div class="flex items-center gap-2">
        <span class="text-sm text-gray-500">Итоговая оценка:</span>
        <span
          v-if="attemptsData.final_score !== null"
          class="text-sm font-semibold"
          :class="attemptsData.is_passed ? 'text-green-600' : 'text-red-600'"
        >
          {{ Math.round(attemptsData.final_score * 100) }}%
        </span>
        <span v-else class="text-sm text-gray-400">—</span>
        <span
          v-if="attemptsData.is_manual"
          class="text-xs bg-violet-100 text-violet-700 px-2 py-0.5 rounded-full"
          title="Выставлен преподавателем"
        >вручную</span>
        <span
          v-if="attemptsData.is_passed"
          class="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full"
        >Сдан</span>
        <span
          v-else
          class="text-xs bg-rose-100 text-rose-700 px-2 py-0.5 rounded-full"
        >Не сдан</span>
      </div>
    </div>

    <table class="w-full text-sm">
      <thead>
        <tr class="text-left text-gray-500 border-b border-gray-100">
          <th class="pb-2 font-medium w-10">№</th>
          <th class="pb-2 font-medium">Дата</th>
          <th class="pb-2 font-medium text-center">Балл</th>
          <th class="pb-2 font-medium text-center">Результат</th>
        </tr>
      </thead>
      <tbody class="divide-y divide-gray-50">
        <tr
          v-for="a in attemptsData.attempts"
          :key="a.id"
          class="text-gray-700"
        >
          <td class="py-2 tabular-nums">{{ a.attempt_number }}</td>
          <td class="py-2 tabular-nums text-gray-500 text-xs">{{ fmtDate(a.attempted_at) }}</td>
          <td class="py-2 text-center tabular-nums font-medium"
            :class="a.passed ? 'text-green-600' : 'text-red-600'"
          >
            <span v-if="a.score !== null">{{ Math.round(a.score * 100) }}%</span>
            <span v-else class="text-gray-400 font-normal">—</span>
          </td>
          <td class="py-2 text-center">
            <span v-if="a.passed === true" title="Сдан">✓</span>
            <span v-else-if="a.passed === false" class="text-red-500" title="Не сдан">✗</span>
            <span v-else class="text-gray-500 text-xs">проверка…</span>
          </td>
        </tr>
      </tbody>
    </table>
  </section>
</template>
