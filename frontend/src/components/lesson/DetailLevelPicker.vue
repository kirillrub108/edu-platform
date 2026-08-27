<script setup lang="ts">
import type { DetailLevelOption, DetailLevelValue } from '~/composables/useLessonDuration'

defineProps<{
  /** Auto mode reshapes the vision LLM's output; manual mode reshapes the author's own text. */
  isManual: boolean
  options: DetailLevelOption[]
  detailLevel: DetailLevelValue
  durationLabels: Record<string, string | null>
  actualDurationLabel: string | null
  /** True once there's something to estimate from (slides in auto, script text in manual). */
  hasContent: boolean
  error: string
}>()

const emit = defineEmits<{ select: [value: DetailLevelValue] }>()
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
