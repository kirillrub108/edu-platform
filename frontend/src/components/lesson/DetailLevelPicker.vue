<script setup lang="ts">
import type { DetailLevelOption, DetailLevelValue } from '~/composables/useLessonDuration'

const props = defineProps<{
  /** Auto mode reshapes the vision LLM's output; manual mode reshapes the author's own text. */
  isManual: boolean
  options: DetailLevelOption[]
  detailLevel: DetailLevelValue
  durationLabels: Record<string, string | null>
  actualDurationLabel: string | null
  /** True once there's something to estimate from (slides in auto, script text in manual). */
  hasContent: boolean
  error: string
  /** Auto mode only: free-form author notes for the vision LLM. */
  narrationBrief?: string
  briefError?: string
}>()

const emit = defineEmits<{
  select: [value: DetailLevelValue]
  'save-brief': [value: string]
}>()

// Mirrors NARRATION_BRIEF_MAX_CHARS in backend/app/constants.py — the backend
// rejects anything longer, this only keeps the user from hitting that 422.
const BRIEF_MAX_CHARS = 1000

const BRIEF_PRESETS = [
  'Аудитория — 9 класс',
  'Не углубляться в математику',
  'Больше практических примеров',
  'Английские термины произносить по-русски',
  'Не пересказывать формулы вслух',
]

// Collapsed by default; opens by itself once a saved brief arrives (the lesson
// loads after mount, so the watch below is the usual trigger).
const briefOpen = ref(!!props.narrationBrief)
const briefDraft = ref(props.narrationBrief ?? '')

watch(() => props.narrationBrief, (value) => {
  briefDraft.value = value ?? ''
  if (value) briefOpen.value = true
})

const briefTooLong = computed(() => briefDraft.value.length > BRIEF_MAX_CHARS)

const addPreset = (preset: string) => {
  const current = briefDraft.value.trim()
  if (current.includes(preset)) return
  briefDraft.value = current ? `${current}\n${preset}` : preset
}

/** Saved on blur — same PUT the level selector uses, no separate save button. */
const commitBrief = () => {
  if (briefTooLong.value) return
  if (briefDraft.value.trim() === (props.narrationBrief ?? '').trim()) return
  emit('save-brief', briefDraft.value)
}
</script>

<template>
  <section class="bg-white rounded-2xl border border-gray-100 p-6 shadow-soft">
    <h3 class="text-sm font-medium text-gray-700">Степень раскрытия темы</h3>
    <p class="text-xs text-gray-400 mt-1 mb-3">
      {{ isManual
        ? 'Что сделать с вашим текстом лекции перед озвучкой. «Как есть» ничего не меняет — остальные варианты сжимают или дополняют его.'
        : 'Насколько подробно LLM разберёт каждый слайд. От этого зависит длительность урока — титульный и заключительный слайды в любом случае короче остальных.' }}
    </p>

    <div class="grid gap-2 sm:grid-cols-3">
      <button
        v-for="opt in options"
        :key="opt.value"
        type="button"
        class="text-left px-3 py-2.5 rounded-xl border transition"
        :class="detailLevel === opt.value
          ? 'border-violet-400 bg-violet-50'
          : 'border-gray-200 hover:bg-gray-50'"
        @click="emit('select', opt.value)"
      >
        <span class="flex items-baseline justify-between gap-2">
          <span
            class="text-sm font-medium"
            :class="detailLevel === opt.value ? 'text-violet-700' : 'text-gray-700'"
          >{{ opt.label }}</span>
          <span
            v-if="durationLabels[opt.value]"
            class="text-xs tabular-nums shrink-0"
            :class="detailLevel === opt.value ? 'text-violet-600' : 'text-gray-400'"
          >{{ durationLabels[opt.value] }}</span>
        </span>
        <span class="block text-xs text-gray-400 mt-1">{{ opt.hint }}</span>
      </button>
    </div>

    <p v-if="!hasContent" class="text-xs text-gray-400 mt-3">
      {{ isManual
        ? 'Добавьте текст лекции — и рядом с каждым вариантом появится примерная длительность урока.'
        : 'Загрузите презентацию — и рядом с каждым вариантом появится примерная длительность урока.' }}
    </p>
    <div v-if="!isManual" class="mt-4 border-t border-gray-100 pt-4">
      <button
        type="button"
        class="flex items-center gap-2 text-sm font-medium text-gray-700 hover:text-violet-700"
        @click="briefOpen = !briefOpen"
      >
        <svg
          class="w-4 h-4 text-gray-400 transition-transform"
          :class="briefOpen ? 'rotate-90' : ''"
          fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"
        >
          <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
        </svg>
        Уточнения для ИИ — необязательно
        <span
          v-if="!briefOpen && (narrationBrief ?? '').trim()"
          class="text-xs text-violet-600"
        >заполнено</span>
      </button>

      <div v-if="briefOpen" class="mt-3">
        <textarea
          v-model="briefDraft"
          rows="3"
          placeholder="Аудитория, акценты, терминология, чего не касаться"
          class="w-full text-sm rounded-xl border px-3 py-2 focus:outline-none focus:ring-2 focus:ring-violet-200"
          :class="briefTooLong ? 'border-rose-300' : 'border-gray-200'"
          @blur="commitBrief"
        />
        <div class="flex items-center justify-between gap-3 mt-1">
          <p class="text-xs text-gray-400">
            Влияет на содержание озвучки — не на её объём.
          </p>
          <span
            class="text-xs tabular-nums shrink-0"
            :class="briefTooLong ? 'text-rose-600' : 'text-gray-400'"
          >{{ briefDraft.length }} / {{ BRIEF_MAX_CHARS }}</span>
        </div>
        <p v-if="briefTooLong" class="text-xs text-rose-600 mt-1">
          Слишком длинно — сократите текст, иначе уточнения не сохранятся.
        </p>

        <div class="flex flex-wrap gap-2 mt-3">
          <button
            v-for="preset in BRIEF_PRESETS"
            :key="preset"
            type="button"
            class="text-xs px-2.5 py-1 rounded-full border border-gray-200 text-gray-600 hover:border-violet-300 hover:text-violet-700"
            @click="addPreset(preset)"
          >+ {{ preset }}</button>
        </div>
        <p v-if="briefError" class="text-sm text-rose-600 mt-2">{{ briefError }}</p>
      </div>
    </div>

    <p v-if="actualDurationLabel" class="text-sm text-gray-500 mt-3">
      Фактическая длительность:
      <span class="font-medium text-gray-800">{{ actualDurationLabel }}</span>
    </p>
    <p v-if="!isManual" class="text-xs text-amber-700 mt-3">
      Применяется во время анализа презентации. Если тексты слайдов уже
      сгенерированы — запустите анализ заново, иначе ничего не изменится.
    </p>
    <p v-else class="text-xs text-gray-400 mt-3">
      Применяется при генерации видео. Сам текст лекции остаётся нетронутым —
      меняется только то, что будет озвучено.
    </p>
    <p v-if="error" class="text-sm text-rose-600 mt-2">{{ error }}</p>
  </section>
</template>
