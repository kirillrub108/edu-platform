<script setup lang="ts">
import { Coins, Loader2, AlertCircle, Gift } from 'lucide-vue-next'

const props = defineProps<{
  open: boolean
  kind: 'video' | 'analyze'
  estimate: any | null
  loading: boolean
}>()

const emit = defineEmits<{
  confirm: []
  close: []
}>()

const cost = computed<number | null>(() => {
  if (!props.estimate) return null
  return props.kind === 'video'
    ? props.estimate.video?.credits ?? null
    : props.estimate.vision_credits ?? null
})

// Both video and analysis share the lecture trial counter.
const trialAvailable = computed(() => !!props.estimate?.trial?.video_trial_available)

const trialLeft = computed(() => {
  const t = props.estimate?.trial
  if (!t) return 0
  return Math.max(0, (t.lectures_limit ?? 0) - (t.lectures_used ?? 0))
})

const insufficient = computed(() => {
  if (!props.estimate || trialAvailable.value) return false
  if (cost.value === null) return false
  return cost.value > (props.estimate.available ?? 0)
})

const title = computed(() =>
  props.kind === 'video' ? 'Запуск генерации видео' : 'Запуск анализа презентации',
)
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4"
      @click.self="emit('close')"
    >
      <div class="bg-white rounded-2xl shadow-xl p-6 w-full max-w-md space-y-4">
        <div class="flex items-start gap-3">
          <div class="w-10 h-10 rounded-xl bg-violet-100 text-violet-600 grid place-items-center shrink-0">
            <Coins class="w-5 h-5" />
          </div>
          <div>
            <h3 class="text-base font-semibold text-gray-900">{{ title }}</h3>
            <p class="text-sm text-gray-500 mt-1">
              Проверьте стоимость операции перед запуском.
            </p>
          </div>
        </div>

        <div v-if="loading" class="flex items-center gap-2 text-sm text-gray-500 py-2">
          <Loader2 class="w-4 h-4 animate-spin" />
          Считаем стоимость…
        </div>

        <template v-else-if="estimate">
          <div
            v-if="trialAvailable"
            class="flex items-center gap-2 text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-xl px-3 py-2"
          >
            <Gift class="w-4 h-4 shrink-0" />
            Бесплатно по триалу (осталось {{ trialLeft }} из {{ estimate.trial?.lectures_limit ?? 0 }} лекций)
          </div>

          <div v-else class="space-y-1.5 text-sm">
            <div class="flex items-center justify-between">
              <span class="text-gray-600">Стоимость:</span>
              <span class="font-semibold tabular-nums text-gray-900">
                {{ cost === null ? '—' : `${cost} CR` }}
              </span>
            </div>
            <div class="flex items-center justify-between">
              <span class="text-gray-600">Доступно:</span>
              <span class="font-semibold tabular-nums text-gray-900">{{ estimate.available ?? 0 }} CR</span>
            </div>
          </div>

          <div
            v-if="insufficient"
            class="flex items-start gap-2 text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-xl px-3 py-2"
          >
            <AlertCircle class="w-4 h-4 shrink-0 mt-0.5" />
            <span class="flex-1">Недостаточно кредитов для запуска.</span>
            <NuxtLink
              to="/billing"
              class="shrink-0 text-xs font-medium text-violet-700 hover:text-violet-800 whitespace-nowrap"
              @click="emit('close')"
            >
              Пополнить →
            </NuxtLink>
          </div>
        </template>

        <div class="flex justify-end gap-2 pt-1">
          <UiButton variant="secondary" @click="emit('close')">Отмена</UiButton>
          <UiButton
            variant="primary"
            :disabled="loading || insufficient"
            @click="emit('confirm')"
          >
            Запустить
          </UiButton>
        </div>
      </div>
    </div>
  </Teleport>
</template>
