<script setup lang="ts">
import {
  Sparkles, ShieldCheck, Trash2, Plus, RotateCcw, AlertTriangle, CheckCircle2,
} from 'lucide-vue-next'
import UiButton from './UiButton.vue'
import type { TeacherQuizQuestion, RegenerateMode } from '../composables/useQuizAuthoring'

interface Props {
  lessonId: string
  initialTaskId?: string | null
}

const props = defineProps<Props>()

const lessonIdRef = computed(() => props.lessonId)
const {
  questions, loading, loadError,
  generating, generationStep, generationDone, generationTotal, generationError,
  regenIds, savingIds, flags, qaRunning, qaError, flagFor,
  load, generate, patchQuestion, regenerate, deleteQuestion, runQaReview,
  resumeIfRunning,
} = useQuizAuthoring(lessonIdRef)

const REGEN_MODES: { value: RegenerateMode; label: string }[] = [
  { value: 'rephrase', label: 'Перефразировать' },
  { value: 'harder', label: 'Сложнее' },
  { value: 'easier', label: 'Проще' },
  { value: 'improve_distractors', label: 'Улучшить дистракторы' },
]

const editBuffers = ref<Record<string, { question: string; options: string[] }>>({})
const saveTimers = ref<Record<string, ReturnType<typeof setTimeout>>>({})

const syncBuffer = (q: TeacherQuizQuestion) => {
  editBuffers.value[q.id] = {
    question: q.question,
    options: [...q.options],
  }
}

watch(questions, (rows) => {
  for (const q of rows) {
    if (!editBuffers.value[q.id]) syncBuffer(q)
  }
  // Drop buffers for questions that no longer exist.
  for (const id of Object.keys(editBuffers.value)) {
    if (!rows.find(r => r.id === id)) delete editBuffers.value[id]
  }
}, { deep: false })

const scheduleSave = (q: TeacherQuizQuestion, patch: Partial<TeacherQuizQuestion>) => {
  if (saveTimers.value[q.id]) clearTimeout(saveTimers.value[q.id])
  saveTimers.value[q.id] = setTimeout(async () => {
    try {
      await patchQuestion(q, patch)
    } catch {
      // Reload to discard local edits on conflict.
      await load()
    }
  }, 500)
}

const onQuestionInput = (q: TeacherQuizQuestion) => {
  const buf = editBuffers.value[q.id]
  if (!buf) return
  scheduleSave(q, { question: buf.question })
}

const onOptionInput = (q: TeacherQuizQuestion, idx: number) => {
  const buf = editBuffers.value[q.id]
  if (!buf) return
  scheduleSave(q, { options: [...buf.options] })
}

const setCorrect = async (q: TeacherQuizQuestion, idx: number) => {
  if (q.correct_index === idx) return
  try {
    await patchQuestion(q, { correct_index: idx })
  } catch (e: any) {
    // 422 OOR — extremely unlikely since idx is within current options, but surface anyway.
    alert(e?.data?.detail ?? 'Не удалось сохранить правильный ответ')
  }
}

const onRegenerate = async (q: TeacherQuizQuestion, mode: RegenerateMode) => {
  try {
    await regenerate(q, mode)
    syncBuffer(questions.value.find(x => x.id === q.id) ?? q)
  } catch (e: any) {
    alert(e?.data?.detail ?? 'Не удалось перегенерировать вопрос')
  }
}

const onDelete = async (q: TeacherQuizQuestion) => {
  if (!confirm('Удалить вопрос?')) return
  await deleteQuestion(q)
}

const onGenerate = async () => {
  if (questions.value.length > 0) {
    if (!confirm('Существующие вопросы будут заменены. Продолжить?')) return
  }
  await generate()
}

const flagBadge = (kind: string) => {
  switch (kind) {
    case 'wrong_answer': return { label: 'Неверный ответ', color: 'rose' }
    case 'ambiguous':    return { label: 'Неоднозначно',   color: 'amber' }
    case 'duplicate':    return { label: 'Дубликат',        color: 'violet' }
    default:             return { label: 'OK',              color: 'emerald' }
  }
}

onMounted(async () => {
  await load()
  if (props.initialTaskId) resumeIfRunning(props.initialTaskId)
})

onUnmounted(() => {
  for (const t of Object.values(saveTimers.value)) clearTimeout(t)
})
</script>

<template>
  <section class="bg-white rounded-2xl border border-gray-100 shadow-soft p-5 space-y-4">
    <header class="flex items-center justify-between gap-3 flex-wrap">
      <div>
        <h2 class="text-lg font-semibold text-gray-900">Тест по уроку</h2>
        <p class="text-sm text-gray-500">
          Вопросы автоматически генерируются из материалов урока. Их можно редактировать вручную или с помощью ИИ.
        </p>
      </div>
      <div class="flex flex-wrap gap-2">
        <UiButton
          variant="primary"
          size="sm"
          :loading="generating"
          @click="onGenerate"
        >
          <template #icon><Sparkles class="w-4 h-4" /></template>
          {{ questions.length ? 'Перегенерировать' : 'Сгенерировать тест' }}
        </UiButton>
        <UiButton
          variant="secondary"
          size="sm"
          :loading="qaRunning"
          :disabled="!questions.length || generating"
          @click="runQaReview"
        >
          <template #icon><ShieldCheck class="w-4 h-4" /></template>
          AI-проверка
        </UiButton>
      </div>
    </header>

    <div
      v-if="generating"
      class="text-sm text-violet-700 bg-violet-50 border border-violet-200 rounded-xl px-3 py-2"
    >
      Генерация теста…
      <span v-if="generationStep">
        ({{ generationStep }} {{ generationDone }}/{{ generationTotal }})
      </span>
    </div>

    <div
      v-if="generationError"
      class="text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-xl px-3 py-2"
    >
      {{ generationError }}
    </div>

    <div
      v-if="qaError"
      class="text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-xl px-3 py-2"
    >
      {{ qaError }}
    </div>

    <div v-if="loading" class="text-sm text-gray-500">Загрузка вопросов…</div>

    <div
      v-else-if="loadError"
      class="text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-xl p-3"
    >
      {{ loadError }}
    </div>

    <div
      v-else-if="questions.length === 0 && !generating"
      class="text-sm text-gray-500 bg-violet-50/40 border border-violet-100 rounded-2xl p-6 text-center"
    >
      Тест ещё не создан. Нажмите «Сгенерировать тест», чтобы автоматически собрать вопросы из материалов урока.
    </div>

    <ol v-else class="space-y-4">
      <li
        v-for="(q, qIdx) in questions"
        :key="q.id"
        class="rounded-2xl border border-gray-100 p-4 bg-gray-50/60"
      >
        <div class="flex items-start justify-between gap-3 mb-3">
          <div class="flex-1">
            <label class="block text-xs font-medium text-gray-500 mb-1">
              Вопрос {{ qIdx + 1 }}
            </label>
            <textarea
              v-if="editBuffers[q.id]"
              v-model="editBuffers[q.id].question"
              rows="2"
              class="w-full resize-none px-3 py-2 text-sm bg-white border border-gray-200 rounded-lg
                     focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400 transition"
              @input="onQuestionInput(q)"
            />
          </div>

          <div class="flex flex-col items-end gap-1">
            <div v-if="flagFor(q.id)" class="text-xs">
              <span
                :class="[
                  'inline-flex items-center gap-1 px-2 py-0.5 rounded-full border',
                  flagBadge(flagFor(q.id)!.kind).color === 'emerald'
                    ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
                    : flagBadge(flagFor(q.id)!.kind).color === 'rose'
                      ? 'bg-rose-50 border-rose-200 text-rose-700'
                      : flagBadge(flagFor(q.id)!.kind).color === 'amber'
                        ? 'bg-amber-50 border-amber-200 text-amber-700'
                        : 'bg-violet-50 border-violet-200 text-violet-700',
                ]"
              >
                <CheckCircle2 v-if="flagFor(q.id)!.kind === 'ok'" class="w-3 h-3" />
                <AlertTriangle v-else class="w-3 h-3" />
                {{ flagBadge(flagFor(q.id)!.kind).label }}
              </span>
            </div>
            <div v-if="savingIds.has(q.id)" class="text-[10px] text-violet-500">сохранение…</div>
          </div>
        </div>

        <div
          v-if="flagFor(q.id)?.note"
          class="text-xs text-gray-600 italic mb-3 px-1"
        >
          {{ flagFor(q.id)!.note }}
        </div>

        <ul class="space-y-2">
          <li
            v-for="(opt, oIdx) in editBuffers[q.id]?.options ?? []"
            :key="oIdx"
            class="flex items-center gap-2"
          >
            <input
              type="radio"
              :name="`correct-${q.id}`"
              :checked="q.correct_index === oIdx"
              class="accent-violet-600"
              @change="setCorrect(q, oIdx)"
            />
            <input
              v-model="editBuffers[q.id].options[oIdx]"
              class="flex-1 px-3 py-1.5 text-sm bg-white border border-gray-200 rounded-lg
                     focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400 transition"
              @input="onOptionInput(q, oIdx)"
            />
          </li>
        </ul>

        <div class="flex flex-wrap gap-2 mt-3">
          <div class="flex gap-1 flex-wrap">
            <UiButton
              v-for="m in REGEN_MODES"
              :key="m.value"
              variant="ghost"
              size="sm"
              :loading="regenIds.has(q.id)"
              :disabled="regenIds.has(q.id)"
              @click="onRegenerate(q, m.value)"
            >
              <template #icon><RotateCcw class="w-3 h-3" /></template>
              {{ m.label }}
            </UiButton>
          </div>
          <UiButton variant="ghost" size="sm" @click="onDelete(q)">
            <template #icon><Trash2 class="w-3 h-3" /></template>
            Удалить
          </UiButton>
        </div>
      </li>
    </ol>
  </section>
</template>
