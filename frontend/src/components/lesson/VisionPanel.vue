<script setup lang="ts">
import { Sparkles, ChevronDown, AlertCircle, Square } from 'lucide-vue-next'

const slideEditorRef = ref()

defineExpose({
  takeSnapshot: () => slideEditorRef.value?.takeSnapshot(),
  clearSnapshot: () => slideEditorRef.value?.clearSnapshot(),
  restoreFromSnapshot: () => slideEditorRef.value?.restoreFromSnapshot(),
})

defineProps<{
  hasPptx: boolean
  analyzing: boolean
  analyzeStatus: string
  analyzeStep: string
  progressDone: number
  progressTotal: number
  analyzeError: string
  generating: boolean
  lessonStatus: string
  showSlideEditor: boolean
  lessonId: string
  cancellingAnalysis: boolean
  creditsSpent: number
  creditsReserved: number
  billedVia: string | null
  needTopup: boolean
}>()

const emit = defineEmits<{
  'start-analyze': []
  'cancel-analyze': []
  'toggle-slide-editor': []
  'slide-back': []
  'slide-ready': []
}>()

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
  emit('cancel-analyze')
}

const onCancelDecline = () => {
  confirmCancel.value = false
  clearConfirmTimer()
}

onUnmounted(clearConfirmTimer)
</script>

<template>
  <div class="space-y-6">
    <!-- Analysis trigger -->
    <section class="bg-white rounded-2xl border border-gray-100 p-6 shadow-soft">
      <h2 class="text-lg font-semibold text-gray-900 mb-1">Автогенерация текста по слайдам</h2>
      <p class="text-sm text-gray-500 mb-4">
        Vision LLM проанализирует каждый слайд и напишет развёрнутый текст озвучки.
      </p>

      <div v-if="analyzing || analyzeStatus === 'PROGRESS'" class="mb-4">
        <div class="text-sm text-violet-700 mb-2 flex items-center gap-1.5">
          <Sparkles class="w-4 h-4 animate-pulse" />
          <template v-if="analyzeStep === 'slides'">Подготовка слайдов…</template>
          <template v-else-if="analyzeStep === 'vision'">
            Анализируется слайд {{ progressDone }} из {{ progressTotal || '…' }}
          </template>
          <template v-else>Запуск анализа…</template>
        </div>
        <ProgressBar
          :value="progressDone"
          :total="progressTotal"
          :indeterminate="progressTotal === 0"
        />
        <p class="mt-2 text-xs text-gray-500">
          <template v-if="billedVia === 'trial'">Триальная генерация — бесплатно</template>
          <template v-else>Списано {{ creditsSpent }} из {{ creditsReserved }} CR</template>
        </p>
      </div>

      <div
        v-if="analyzeError"
        class="flex items-start gap-2 mb-3 text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-xl px-3 py-2"
      >
        <AlertCircle class="w-4 h-4 shrink-0 mt-0.5" />
        <span class="flex-1">{{ analyzeError }}</span>
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
          :loading="analyzing"
          :disabled="!hasPptx || generating || lessonStatus === 'processing'"
          @click="emit('start-analyze')"
        >
          <template #icon><Sparkles class="w-4 h-4" /></template>
          {{ (lessonStatus === 'ready_for_edit' || lessonStatus === 'published') ? 'Перезапустить анализ' : 'Запустить анализ' }}
        </UiButton>
        <template v-if="analyzing">
          <UiButton
            v-if="!confirmCancel"
            variant="secondary"
            :loading="cancellingAnalysis"
            @click="onCancelClick"
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
              :loading="cancellingAnalysis"
              @click="onCancelConfirm"
            >
              Да, отменить
            </UiButton>
            <UiButton variant="ghost" size="sm" @click="onCancelDecline">
              Нет
            </UiButton>
          </template>
        </template>
      </div>
    </section>

    <!-- Analysis results / slide editor (collapsible) -->
    <section
      v-if="lessonStatus === 'ready_for_edit' || lessonStatus === 'published'"
      class="bg-white rounded-2xl border border-gray-100 shadow-soft overflow-hidden"
    >
      <button
        type="button"
        class="w-full flex items-center justify-between px-6 py-4 hover:bg-gray-50 transition"
        @click="emit('toggle-slide-editor')"
      >
        <div class="text-left">
          <h2 class="text-lg font-semibold text-gray-900">Результаты анализа</h2>
          <p class="text-sm text-gray-500">Текст озвучки по слайдам — можно редактировать</p>
        </div>
        <ChevronDown
          class="w-5 h-5 text-gray-400 transition-transform duration-200 shrink-0"
          :class="{ 'rotate-180': showSlideEditor }"
        />
      </button>
      <div v-if="showSlideEditor" class="px-6 pb-6">
        <SlideTextEditor
          ref="slideEditorRef"
          :lesson-id="lessonId"
          @back="emit('slide-back')"
          @ready="emit('slide-ready')"
        />
      </div>
    </section>
  </div>
</template>
