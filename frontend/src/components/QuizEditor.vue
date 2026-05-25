<script setup lang="ts">
import {
  Sparkles, ShieldCheck, Trash2, RotateCcw, AlertTriangle, CheckCircle2,
  Eye, EyeOff,
} from 'lucide-vue-next'
import UiButton from './UiButton.vue'
import QuestionForm from './quiz/QuestionForm.vue'
import type {
  TeacherQuestion, RegenerateMode, QuestionType,
} from '../composables/useQuizAuthoring'

interface Props {
  lessonId: string
}

const props = defineProps<Props>()
const lessonIdRef = computed(() => props.lessonId)

const {
  settings, questions, loading, loadError,
  isPublished,
  generating, generationStep, generationDone, generationTotal, generationError,
  regenIds, savingIds,
  flags, qaRunning, qaError, flagFor,
  load, updateSettings, publish, unpublish,
  generate, createQuestion, patchQuestion, deleteQuestion,
  regenerate, runAiReview,
} = useQuizAuthoring(lessonIdRef)

const TYPE_LABELS: Record<QuestionType, string> = {
  single_choice: 'Один из',
  multiple_choice: 'Несколько из',
  true_false: 'Верно/Неверно',
  short_answer: 'Короткий ответ',
  essay: 'Эссе',
  matching: 'Сопоставление',
  ordering: 'Порядок',
  fill_blank: 'Пропуски',
}

const ADDABLE_TYPES: QuestionType[] = [
  'single_choice', 'multiple_choice', 'true_false',
  'short_answer', 'essay', 'matching', 'ordering', 'fill_blank',
]

const REGEN_MODES: { value: RegenerateMode; label: string }[] = [
  { value: 'rephrase', label: 'Перефразировать' },
  { value: 'harder', label: 'Сложнее' },
  { value: 'easier', label: 'Проще' },
  { value: 'improve_distractors', label: 'Улучшить дистракторы' },
]

// Debounced payload PATCH per question.
const saveTimers = ref<Record<string, ReturnType<typeof setTimeout>>>({})

const schedulePayloadPatch = (q: TeacherQuestion, payload: Record<string, any>) => {
  if (saveTimers.value[q.id]) clearTimeout(saveTimers.value[q.id])
  saveTimers.value[q.id] = setTimeout(async () => {
    try {
      await patchQuestion(q, { payload })
    } catch {
      await load()
    }
  }, 500)
}

// Debounced settings PUT.
let settingsTimer: ReturnType<typeof setTimeout> | null = null
const scheduleSettingsPatch = (patch: Record<string, any>) => {
  if (settingsTimer) clearTimeout(settingsTimer)
  settingsTimer = setTimeout(() => updateSettings(patch), 300)
}

const onAddQuestion = async (type: QuestionType) => {
  const payload = defaultPayload(type)
  await createQuestion(type, payload, 1.0)
}

const defaultPayload = (type: QuestionType): Record<string, any> => {
  switch (type) {
    case 'single_choice':
      return { type, prompt: 'Введите вопрос', options: ['Вариант 1', 'Вариант 2'], correct_index: 0, explanation: '' }
    case 'multiple_choice':
      return { type, prompt: 'Введите вопрос', options: ['Вариант 1', 'Вариант 2', 'Вариант 3'], correct_indices: [0], explanation: '' }
    case 'true_false':
      return { type, prompt: 'Введите утверждение', correct: true, explanation: '' }
    case 'short_answer':
      return { type, prompt: 'Введите вопрос', reference_answer: 'Эталонный ответ', rubric: '' }
    case 'essay':
      return { type, prompt: 'Введите вопрос', rubric: 'Критерии оценки' }
    case 'matching':
      return { type, prompt: 'Сопоставьте элементы', left: ['Элемент 1', 'Элемент 2'], right: ['Пара 1', 'Пара 2'], correct_pairs: [[0, 0], [1, 1]], explanation: '' }
    case 'ordering':
      return { type, prompt: 'Упорядочьте элементы', items: ['Элемент 1', 'Элемент 2'], correct_order: [0, 1], explanation: '' }
    case 'fill_blank':
      return { type, prompt: 'Введите текст с ___ пропуском.', blanks: [['ответ']], case_insensitive: true, explanation: '' }
  }
}

const onRegenerate = async (q: TeacherQuestion, mode: RegenerateMode) => {
  try {
    await regenerate(q, mode)
  } catch (e: any) {
    alert(e?.data?.detail ?? 'Не удалось перегенерировать вопрос')
  }
}

const onDelete = async (q: TeacherQuestion) => {
  if (!confirm('Удалить вопрос?')) return
  await deleteQuestion(q)
}

// Generation modal state
const GENERATABLE_TYPES: { value: QuestionType; label: string }[] = [
  { value: 'single_choice',   label: 'Один из' },
  { value: 'multiple_choice', label: 'Несколько из' },
  { value: 'true_false',      label: 'Верно/Неверно' },
  { value: 'short_answer',    label: 'Короткий ответ' },
]

const showGenModal = ref(false)
const genNumQuestions = ref(5)
const genTypes = ref<QuestionType[]>(['single_choice', 'multiple_choice', 'true_false', 'short_answer'])

const toggleGenType = (type: QuestionType) => {
  const idx = genTypes.value.indexOf(type)
  if (idx === -1) {
    genTypes.value.push(type)
  } else if (genTypes.value.length > 1) {
    genTypes.value.splice(idx, 1)
  }
}

const onGenerate = () => {
  showGenModal.value = true
}

const onConfirmGenerate = async () => {
  if (questions.value.length > 0) {
    if (!confirm('Существующие вопросы будут заменены. Продолжить?')) return
  }
  showGenModal.value = false
  await generate(genNumQuestions.value, 4, genTypes.value)
}

const flagBadge = (kind: string) => {
  switch (kind) {
    case 'wrong_answer': return { label: 'Неверный ответ', color: 'rose' }
    case 'ambiguous':    return { label: 'Неоднозначно',   color: 'amber' }
    case 'duplicate':    return { label: 'Дубликат',        color: 'violet' }
    default:             return { label: 'OK',              color: 'emerald' }
  }
}

const onTogglePublish = async () => {
  if (isPublished.value) await unpublish()
  else await publish()
}

onMounted(load)
onUnmounted(() => {
  for (const t of Object.values(saveTimers.value)) clearTimeout(t)
  if (settingsTimer) clearTimeout(settingsTimer)
})
</script>

<template>
  <section class="bg-white rounded-2xl border border-gray-100 shadow-soft p-5 space-y-4">
    <header class="flex items-center justify-between gap-3 flex-wrap">
      <div>
        <h2 class="text-lg font-semibold text-gray-900">Тест по уроку</h2>
        <p class="text-sm text-gray-500">
          Создавайте вопросы вручную или сгенерируйте из текста. Опубликованный тест видят студенты.
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
          @click="runAiReview"
        >
          <template #icon><ShieldCheck class="w-4 h-4" /></template>
          AI-проверка
        </UiButton>
        <UiButton
          v-if="settings"
          :variant="isPublished ? 'ghost' : 'primary'"
          size="sm"
          :disabled="!questions.length"
          @click="onTogglePublish"
        >
          <template #icon>
            <EyeOff v-if="isPublished" class="w-4 h-4" />
            <Eye v-else class="w-4 h-4" />
          </template>
          {{ isPublished ? 'Снять с публикации' : 'Опубликовать' }}
        </UiButton>
      </div>
    </header>

    <!-- Settings -->
    <div
      v-if="settings"
      class="grid grid-cols-2 sm:grid-cols-4 gap-3 rounded-xl bg-gray-50 p-3 text-sm"
    >
      <label class="flex flex-col gap-1">
        <span class="text-xs text-gray-500">Попыток</span>
        <select
          :value="settings.attempts_allowed ?? ''"
          class="rounded-lg border border-gray-200 px-2 py-1"
          @change="(e: any) => scheduleSettingsPatch({
            attempts_allowed: e.target.value === '' ? null : Number(e.target.value),
          })"
        >
          <option value="">∞</option>
          <option value="1">1</option>
          <option value="2">2</option>
          <option value="3">3</option>
          <option value="5">5</option>
        </select>
      </label>
      <label class="flex flex-col gap-1">
        <span class="text-xs text-gray-500">Порог сдачи</span>
        <input
          type="number" min="0" max="1" step="0.05"
          :value="Number(settings.pass_threshold)"
          class="rounded-lg border border-gray-200 px-2 py-1"
          @input="(e: any) => scheduleSettingsPatch({ pass_threshold: e.target.value })"
        />
      </label>
      <label class="flex flex-col gap-1">
        <span class="text-xs text-gray-500">Показывать ответы</span>
        <select
          :value="String(settings.show_answers)"
          :disabled="settings.attempts_allowed !== 1"
          class="rounded-lg border border-gray-200 px-2 py-1 disabled:bg-gray-100 disabled:text-gray-400"
          @change="(e: any) => scheduleSettingsPatch({ show_answers: e.target.value === 'true' })"
        >
          <option value="true">Да</option>
          <option value="false">Нет</option>
        </select>
      </label>
      <label class="flex flex-col gap-1">
        <span class="text-xs text-gray-500">Перемешивать</span>
        <select
          :value="String(settings.shuffle)"
          class="rounded-lg border border-gray-200 px-2 py-1"
          @change="(e: any) => scheduleSettingsPatch({ shuffle: e.target.value === 'true' })"
        >
          <option value="false">Нет</option>
          <option value="true">Да</option>
        </select>
      </label>
      <p
        v-if="settings.attempts_allowed !== 1"
        class="col-span-2 sm:col-span-4 text-xs text-gray-500"
      >
        Правильные ответы показываются только при ровно одной разрешённой попытке.
      </p>
    </div>

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
    >{{ generationError }}</div>

    <div
      v-if="qaError"
      class="text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-xl px-3 py-2"
    >{{ qaError }}</div>

    <div v-if="loading" class="text-sm text-gray-500">Загрузка вопросов…</div>

    <div
      v-else-if="loadError"
      class="text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-xl p-3"
    >{{ loadError }}</div>

    <div
      v-else-if="questions.length === 0 && !generating"
      class="text-sm text-gray-500 bg-violet-50/40 border border-violet-100 rounded-2xl p-6 text-center"
    >
      Тест ещё пуст. Сгенерируйте автоматически или добавьте вопрос вручную ниже.
    </div>

    <ol v-else class="space-y-4">
      <li
        v-for="(q, qIdx) in questions"
        :key="q.id"
        class="rounded-2xl border border-gray-100 p-4 bg-gray-50/60 space-y-3"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="flex items-center gap-2 text-xs">
            <span class="font-medium text-gray-500">Вопрос {{ qIdx + 1 }}</span>
            <span class="px-2 py-0.5 rounded-full bg-white border border-gray-200 text-gray-600">
              {{ TYPE_LABELS[q.type] }}
            </span>
          </div>
          <div class="flex items-center gap-2">
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

        <p
          v-if="flagFor(q.id)?.note"
          class="text-xs text-gray-600 italic"
        >{{ flagFor(q.id)!.note }}</p>

        <QuestionForm
          :type="q.type"
          :payload="q.payload"
          @update="(p) => schedulePayloadPatch(q, p)"
        />

        <div class="flex flex-wrap gap-2 pt-2">
          <UiButton
            v-for="m in REGEN_MODES"
            :key="m.value"
            variant="ghost"
            size="sm"
            :disabled="regenIds.has(q.id) || q.type !== 'single_choice'"
            :loading="regenIds.has(q.id)"
            @click="onRegenerate(q, m.value)"
          >
            <template #icon><RotateCcw class="w-3 h-3" /></template>
            {{ m.label }}
          </UiButton>
          <UiButton variant="ghost" size="sm" @click="onDelete(q)">
            <template #icon><Trash2 class="w-3 h-3" /></template>
            Удалить
          </UiButton>
        </div>
      </li>
    </ol>

    <div class="flex flex-wrap gap-2 pt-2 border-t border-gray-100">
      <span class="text-xs text-gray-500 mr-1 self-center">Добавить вопрос:</span>
      <button
        v-for="t in ADDABLE_TYPES"
        :key="t"
        type="button"
        class="text-xs px-2 py-1 rounded-lg border border-gray-200 text-gray-700 hover:bg-violet-50 transition"
        @click="onAddQuestion(t)"
      >+ {{ TYPE_LABELS[t] }}</button>
    </div>

    <!-- Generation modal -->
    <Teleport to="body">
      <div
        v-if="showGenModal"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
        @click.self="showGenModal = false"
      >
        <div class="bg-white rounded-2xl shadow-xl p-6 w-full max-w-sm space-y-5">
          <h3 class="text-base font-semibold text-gray-900">Настройки генерации</h3>

          <label class="flex flex-col gap-1">
            <span class="text-sm text-gray-600">Количество вопросов</span>
            <input
              v-model.number="genNumQuestions"
              type="number" min="1" max="20"
              class="rounded-lg border border-gray-200 px-3 py-1.5 text-sm w-24"
            />
          </label>

          <div class="flex flex-col gap-2">
            <span class="text-sm text-gray-600">Типы вопросов</span>
            <div class="flex flex-col gap-1.5">
              <label
                v-for="t in GENERATABLE_TYPES"
                :key="t.value"
                class="flex items-center gap-2 cursor-pointer text-sm"
              >
                <input
                  type="checkbox"
                  :checked="genTypes.includes(t.value)"
                  class="accent-violet-600"
                  @change="toggleGenType(t.value)"
                />
                {{ t.label }}
              </label>
            </div>
          </div>

          <div class="flex justify-end gap-2 pt-1">
            <button
              type="button"
              class="text-sm px-4 py-1.5 rounded-lg border border-gray-200 text-gray-700 hover:bg-gray-50 transition"
              @click="showGenModal = false"
            >Отмена</button>
            <button
              type="button"
              class="text-sm px-4 py-1.5 rounded-lg bg-violet-600 text-white hover:bg-violet-700 transition disabled:opacity-50"
              :disabled="genTypes.length === 0"
              @click="onConfirmGenerate"
            >Сгенерировать</button>
          </div>
        </div>
      </div>
    </Teleport>
  </section>
</template>
