<script setup lang="ts">
import { ArrowDown, Video, Square, AlertCircle } from 'lucide-vue-next'

const props = defineProps<{
  voices: Array<{ value: string; label: string }>
  selectedVoice: string
  generating: boolean
  cancellingVideo: boolean
  lessonStatus: string
  showPipeline: boolean
  pipelineStages: Array<{ label: string; pct?: number }>
  currentStageIdx: number
  taskError: string
  canGenerateVideo: boolean
  videoUrl: string | null
  analyzing: boolean
  hasPptx: boolean
  isAuto: boolean
  isManual: boolean
  scriptIsEmpty: boolean
}>()

const emit = defineEmits<{
  'update:selectedVoice': [voice: string]
  generate: []
  cancel: []
}>()

const isProcessing = computed(() => props.generating || props.lessonStatus === 'processing')

const hint = computed(() => {
  if (!props.hasPptx) return 'Сначала загрузите презентацию'
  if (props.isAuto && props.analyzing) return 'Дождитесь завершения анализа'
  if (props.isAuto && props.lessonStatus !== 'ready_for_edit' && props.lessonStatus !== 'published') {
    return 'Сначала запустите анализ презентации'
  }
  if (props.isManual && props.scriptIsEmpty) return 'Введите текст доклада'
  return ''
})
</script>

<template>
  <div class="space-y-6">
    <section class="bg-white rounded-2xl border border-gray-100 p-6 shadow-soft">
      <h2 class="text-lg font-semibold text-gray-900 mb-1">Генерация видео</h2>
      <p class="text-sm text-gray-500 mb-5">
        Запустите пайплайн: слайды + озвучка → MP4. Займёт 1–5 минут.
      </p>

      <div class="mb-5 max-w-xs">
        <label class="block text-sm font-medium text-gray-700 mb-1.5">Голос озвучки</label>
        <div class="relative">
          <select
            :value="selectedVoice"
            :disabled="isProcessing"
            class="w-full bg-white border border-gray-200 rounded-xl px-4 py-2.5 text-sm appearance-none pr-9 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400 disabled:opacity-50 transition"
            @change="emit('update:selectedVoice', ($event.target as HTMLSelectElement).value)"
          >
            <option v-for="v in voices" :key="v.value" :value="v.value">{{ v.label }}</option>
          </select>
          <ArrowDown class="w-4 h-4 absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
        </div>
      </div>

      <div v-if="showPipeline" class="mb-5 px-2">
        <PipelineStages :stages="pipelineStages" :current="currentStageIdx" />
      </div>

      <div
        v-if="taskError"
        class="flex items-start gap-2 mb-3 text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-xl px-3 py-2"
      >
        <AlertCircle class="w-4 h-4 shrink-0 mt-0.5" />
        <span>{{ taskError }}</span>
      </div>

      <div class="flex gap-2 flex-wrap items-center">
        <UiButton
          variant="primary"
          :loading="isProcessing"
          :disabled="!canGenerateVideo"
          @click="emit('generate')"
        >
          <template #icon><Video class="w-4 h-4" /></template>
          <span v-if="isProcessing">Генерируется…</span>
          <span v-else-if="lessonStatus === 'published'">Перегенерировать</span>
          <span v-else>Создать видео</span>
        </UiButton>
        <UiButton
          v-if="isProcessing"
          variant="secondary"
          :loading="cancellingVideo"
          type="button"
          @click.prevent="emit('cancel')"
        >
          <template #icon><Square class="w-4 h-4" /></template>
          Остановить
        </UiButton>
      </div>
      <p v-if="!canGenerateVideo && !isProcessing && hint" class="mt-2 text-xs text-gray-400">
        {{ hint }}
      </p>
    </section>

    <!-- Video player -->
    <section
      v-if="lessonStatus === 'published' && videoUrl"
      class="bg-white rounded-2xl border border-gray-100 p-6 shadow-soft"
    >
      <h2 class="text-lg font-semibold text-gray-900 mb-3">Готовое видео</h2>
      <video :src="videoUrl" controls class="w-full rounded-xl bg-black" />
      <a
        :href="videoUrl"
        target="_blank"
        class="mt-3 inline-block text-sm text-violet-700 hover:text-violet-600 font-medium transition"
      >
        Открыть в новой вкладке →
      </a>
    </section>
  </div>
</template>
