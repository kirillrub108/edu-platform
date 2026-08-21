<script setup lang="ts">
import { ArrowDown, Video, Square, AlertCircle } from 'lucide-vue-next'

const props = defineProps<{
  voices: Array<{ value: string; label: string }>
  selectedVoice: string
  selectedSpeed: number
  selectedPitch: number
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
  creditsSpent: number
  creditsReserved: number
  billedVia: string | null
  needTopup: boolean
  cancelled: boolean
  latestPublished: boolean
  publishing: boolean
}>()

const emit = defineEmits<{
  'update:selectedVoice': [voice: string]
  'update:selectedSpeed': [speed: number]
  'update:selectedPitch': [pitch: number]
  generate: []
  cancel: []
  publish: []
  viewHistory: []
  'video-url-expired': []
}>()

const isProcessing = computed(() => props.generating || props.lessonStatus === 'processing')

// Подсказки SpeechKit: 1x / 0 — значения по умолчанию, при них hint не шлётся.
const isDefaultTuning = computed(() => props.selectedSpeed === 1 && props.selectedPitch === 0)
const pitchLabel = computed(() => {
  if (props.selectedPitch === 0) return 'обычная'
  return `${props.selectedPitch > 0 ? 'выше' : 'ниже'} на ${Math.abs(props.selectedPitch)} Гц`
})

function resetTuning() {
  emit('update:selectedSpeed', 1)
  emit('update:selectedPitch', 0)
}

const videoRetried = ref(false)
watch(() => props.videoUrl, () => { videoRetried.value = false })
const onVideoError = () => {
  if (!videoRetried.value) {
    videoRetried.value = true
    emit('video-url-expired')
  }
}

// Two-step cancel: first click flips into confirm mode, which resets after 5s
// of inactivity.
const confirmCancel = ref(false)
let confirmTimer: ReturnType<typeof setTimeout> | null = null

const clearConfirmTimer = () => {
  if (confirmTimer) { clearTimeout(confirmTimer); confirmTimer = null }
}

const onCancelClick = () => {
  confirmCancel.value = true
  clearConfirmTimer()
  confirmTimer = setTimeout(() => { confirmCancel.value = false }, 5000)
}

const onCancelConfirm = () => {
  confirmCancel.value = false
  clearConfirmTimer()
  emit('cancel')
}

const onCancelDecline = () => {
  confirmCancel.value = false
  clearConfirmTimer()
}

onUnmounted(clearConfirmTimer)

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

      <div class="mb-5 rounded-xl border border-gray-200 bg-gray-50/70 p-4">
        <div class="flex items-center justify-between mb-3">
          <span class="text-sm font-medium text-gray-700">Настройка речи</span>
          <button
            v-if="!isDefaultTuning"
            type="button"
            :disabled="isProcessing"
            class="text-xs text-violet-600 hover:text-violet-700 disabled:opacity-50 transition"
            @click="resetTuning"
          >
            Сбросить
          </button>
        </div>

        <div class="grid gap-4 sm:grid-cols-2">
          <div>
            <div class="flex items-baseline justify-between mb-1.5">
              <label class="text-sm text-gray-600">Скорость</label>
              <span class="text-sm font-semibold tabular-nums text-gray-900">
                {{ selectedSpeed.toFixed(1) }}x
              </span>
            </div>
            <input
              type="range"
              min="0.5"
              max="2"
              step="0.1"
              :value="selectedSpeed"
              :disabled="isProcessing"
              class="w-full accent-violet-600 disabled:opacity-50"
              @input="emit('update:selectedSpeed', Number(($event.target as HTMLInputElement).value))"
            >
          </div>

          <div>
            <div class="flex items-baseline justify-between mb-1.5">
              <label class="text-sm text-gray-600">Высота голоса</label>
              <span class="text-sm font-semibold tabular-nums text-gray-900">{{ pitchLabel }}</span>
            </div>
            <input
              type="range"
              min="-500"
              max="500"
              step="50"
              :value="selectedPitch"
              :disabled="isProcessing"
              class="w-full accent-violet-600 disabled:opacity-50"
              @input="emit('update:selectedPitch', Number(($event.target as HTMLInputElement).value))"
            >
          </div>
        </div>
      </div>

      <div v-if="showPipeline" class="mb-5 px-2">
        <PipelineStages :stages="pipelineStages" :current="currentStageIdx" />
        <p class="mt-3 text-xs text-center text-gray-500">
          <template v-if="billedVia === 'trial'">Триальная генерация — бесплатно</template>
          <template v-else>Списано {{ creditsSpent }} из {{ creditsReserved }} CR</template>
        </p>
      </div>

      <div
        v-if="cancelled"
        class="flex items-start gap-2 mb-3 text-sm text-gray-600 bg-gray-50 border border-gray-200 rounded-xl px-3 py-2"
      >
        <AlertCircle class="w-4 h-4 shrink-0 mt-0.5 text-gray-400" />
        <span>Генерация отменена, списано {{ creditsSpent }} CR</span>
      </div>

      <div
        v-if="taskError"
        class="flex items-start gap-2 mb-3 text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-xl px-3 py-2"
      >
        <AlertCircle class="w-4 h-4 shrink-0 mt-0.5" />
        <span class="flex-1">{{ taskError }}</span>
        <NuxtLink
          v-if="needTopup"
          to="/billing"
          class="shrink-0 text-xs font-medium text-violet-700 hover:text-violet-800 whitespace-nowrap"
        >
          Пополнить баланс →
        </NuxtLink>
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
        <template v-if="isProcessing">
          <UiButton
            v-if="!confirmCancel"
            variant="secondary"
            :loading="cancellingVideo"
            type="button"
            @click.prevent="onCancelClick"
          >
            <template #icon><Square class="w-4 h-4" /></template>
            Остановить
          </UiButton>
          <template v-else>
            <span class="text-sm text-gray-600">
              Точно отменить? Спишется за обработанные слайды
            </span>
            <UiButton
              variant="danger"
              size="sm"
              :loading="cancellingVideo"
              type="button"
              @click.prevent="onCancelConfirm"
            >
              Да, отменить
            </UiButton>
            <UiButton variant="ghost" size="sm" type="button" @click.prevent="onCancelDecline">
              Нет
            </UiButton>
          </template>
        </template>
      </div>
      <p v-if="!canGenerateVideo && !isProcessing && hint" class="mt-2 text-xs text-gray-500">
        {{ hint }}
      </p>
    </section>

    <!-- Video player — only once the pipeline is truly done (published + URL).
         Hidden while (re)generating so the old result disappears until the new one lands. -->
    <section
      v-if="lessonStatus === 'published' && videoUrl && !isProcessing"
      class="bg-white rounded-2xl border border-gray-100 p-6 shadow-soft"
    >
      <h2 class="text-lg font-semibold text-gray-900 mb-1">Последнее сгенерированное видео</h2>
      <p class="text-sm text-gray-500 mb-3">
        Предпросмотр последнего результата. Опубликуйте его, чтобы показать студентам.
      </p>
      <video :key="videoUrl" :src="videoUrl" controls class="w-full rounded-xl bg-black" @error="onVideoError" />
      <div class="mt-3 flex flex-wrap items-center gap-2">
        <UiButton
          v-if="!latestPublished"
          variant="primary"
          size="md"
          class="!px-4 !py-2"
          :loading="publishing"
          type="button"
          @click="emit('publish')"
        >
          Опубликовать
        </UiButton>
        <span
          v-else
          class="text-xs bg-violet-100 text-violet-700 px-2.5 py-1 rounded-full font-medium"
        >Опубликовано</span>
        <UiButton variant="secondary" size="md" class="!px-4 !py-2" type="button" @click="emit('viewHistory')">
          Все генерации →
        </UiButton>
        <a
          :href="videoUrl"
          target="_blank"
          class="ml-auto text-sm text-violet-700 hover:text-violet-600 font-medium transition"
        >
          Открыть в новой вкладке →
        </a>
      </div>
    </section>
  </div>
</template>
