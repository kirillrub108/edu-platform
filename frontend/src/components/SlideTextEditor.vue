<script setup lang="ts">
import { ChevronLeft, ChevronRight, Sparkles, Save, FileText, RotateCcw } from 'lucide-vue-next'
import ProgressBar from './ProgressBar.vue'
import UiButton from './UiButton.vue'
import { friendlyApiError } from '~/composables/useBillingMeta'

interface SlideText {
  id: string
  slide_number: number
  image_url: string | null
  generated_text: string
  edited_text: string | null
  is_edited: boolean
}

interface Props {
  lessonId: string
}

const props = defineProps<Props>()
const emit = defineEmits<{ (e: 'ready'): void; (e: 'back'): void }>()

const { apiFetch } = useApi()
const billing = useBillingStore()
const { ensureVerified } = useAiGuard()

const slides = ref<SlideText[]>([])
const regenError = ref('')
const loading = ref(true)
const loadError = ref('')
const currentIdx = ref(0)
const buffer = ref('')
const savingIds = ref<Set<string>>(new Set())
const regenIds = ref<Set<string>>(new Set())
let saveTimer: ReturnType<typeof setTimeout> | null = null

const previousText = ref('')
const canRevert = ref(false)
const regenController = ref<AbortController | null>(null)

const snapshot = ref<SlideText[] | null>(null)
const restoreNotice = ref('')
let restoreNoticeTimer: ReturnType<typeof setTimeout> | null = null

const current = computed<SlideText | null>(() => slides.value[currentIdx.value] ?? null)
const wordsPerMinute = 130

const wordCount = computed(() => buffer.value.trim().split(/\s+/).filter(Boolean).length)
const estDurationLabel = computed(() => {
  const seconds = Math.round((wordCount.value / wordsPerMinute) * 60)
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${s.toString().padStart(2, '0')} мин`
})

const editedCount = computed(() =>
  slides.value.filter(
    s => (s.edited_text ?? '').trim().length > 0 || (s.generated_text ?? '').trim().length > 0,
  ).length,
)

const loadSlides = async () => {
  loading.value = true
  loadError.value = ''
  try {
    const res = await apiFetch<{ slides: SlideText[]; total: number; status: string }>(
      `/lessons/${props.lessonId}/slides`,
    )
    slides.value = res.slides
    if (slides.value.length > 0) {
      currentIdx.value = 0
      buffer.value = current.value?.edited_text ?? current.value?.generated_text ?? ''
    }
  } catch (e: any) {
    loadError.value = e?.data?.detail ?? 'Не удалось загрузить слайды'
  } finally {
    loading.value = false
  }
}

const persistCurrent = async () => {
  const slide = current.value
  if (!slide) return
  if (buffer.value === (slide.edited_text ?? slide.generated_text)) return
  savingIds.value.add(slide.id)
  try {
    const updated = await apiFetch<SlideText>(
      `/lessons/${props.lessonId}/slides/${slide.id}`,
      { method: 'PATCH', body: { edited_text: buffer.value } },
    )
    const idx = slides.value.findIndex(s => s.id === slide.id)
    if (idx >= 0) slides.value[idx] = updated
  } finally {
    savingIds.value.delete(slide.id)
  }
}

const scheduleSave = () => {
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(persistCurrent, 500)
}

const goTo = async (idx: number) => {
  if (idx < 0 || idx >= slides.value.length || idx === currentIdx.value) return
  await persistCurrent()
  currentIdx.value = idx
  buffer.value = current.value?.edited_text ?? current.value?.generated_text ?? ''
}

const next = () => goTo(currentIdx.value + 1)
const prev = () => goTo(currentIdx.value - 1)

const cancelRegen = () => {
  regenController.value?.abort()
}

const revertText = () => {
  buffer.value = previousText.value
  canRevert.value = false
  scheduleSave()
}

const regenerate = async () => {
  const slide = current.value
  if (!slide) return
  // Abort any in-flight regen for this slot before starting a new one
  regenController.value?.abort()
  previousText.value = buffer.value
  canRevert.value = false
  const controller = new AbortController()
  regenController.value = controller
  regenIds.value.add(slide.id)
  regenError.value = ''
  try {
    const updated = await apiFetch<SlideText>(
      `/lessons/${props.lessonId}/slides/${slide.id}/regenerate`,
      { method: 'POST', signal: controller.signal },
    )
    const idx = slides.value.findIndex(s => s.id === slide.id)
    if (idx >= 0) slides.value[idx] = updated
    if (slide.id === current.value?.id) {
      buffer.value = updated.edited_text ?? updated.generated_text ?? ''
      canRevert.value = true
    }
    void billing.refresh()
  } catch (err: any) {
    if (err?.name === 'AbortError' || err?.cause?.name === 'AbortError') return
    // 402 = недостаточно кредитов; detail can be a machine-readable object now.
    regenError.value = friendlyApiError(err).message
    if (err?.response?.status === 402) void billing.fetchBalance()
  } finally {
    regenIds.value.delete(slide.id)
    if (regenController.value === controller) regenController.value = null
  }
}

const guardedRegenerate = () => ensureVerified(regenerate)

const onKeydown = (e: KeyboardEvent) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.preventDefault()
    next()
  } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
    e.preventDefault()
    persistCurrent()
  }
}

const isSavingCurrent = computed(() => current.value && savingIds.value.has(current.value.id))
const isRegenCurrent = computed(() => current.value && regenIds.value.has(current.value.id))

const takeSnapshot = () => {
  snapshot.value = slides.value.map(s => ({ ...s }))
}

const clearSnapshot = () => {
  snapshot.value = null
}

const restoreFromSnapshot = async () => {
  if (!snapshot.value || snapshot.value.length === 0) return
  const toRestore = snapshot.value
  snapshot.value = null
  try {
    const results = await Promise.all(
      toRestore.map(s =>
        apiFetch<SlideText>(
          `/lessons/${props.lessonId}/slides/${s.id}`,
          { method: 'PATCH', body: { edited_text: s.edited_text ?? s.generated_text } },
        ),
      ),
    )
    slides.value = results
    if (slides.value.length > 0) {
      buffer.value = current.value?.edited_text ?? current.value?.generated_text ?? ''
    }
  } catch {
    // restore failed silently — slides.value may be stale, loadSlides() will fix on next open
  }
  // eslint-disable-next-line no-console
  console.warn('[SlideTextEditor] Текст слайдов восстановлен из снапшота')
  if (restoreNoticeTimer) clearTimeout(restoreNoticeTimer)
  restoreNotice.value = 'Текущий текст восстановлен'
  restoreNoticeTimer = setTimeout(() => { restoreNotice.value = '' }, 4000)
}

watch(currentIdx, () => {
  regenController.value?.abort()
  regenController.value = null
  canRevert.value = false
  previousText.value = ''
})

onMounted(() => {
  loadSlides()
  window.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  if (saveTimer) clearTimeout(saveTimer)
  if (restoreNoticeTimer) clearTimeout(restoreNoticeTimer)
  regenController.value?.abort()
})

defineExpose({ persistCurrent, takeSnapshot, clearSnapshot, restoreFromSnapshot })
</script>

<template>
  <div class="space-y-4">
    <div
      v-if="restoreNotice"
      class="text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-xl px-3 py-2"
    >
      {{ restoreNotice }}
    </div>
    <div v-if="loading" class="text-sm text-gray-500">Загрузка слайдов…</div>

    <div
      v-else-if="loadError"
      class="text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-xl p-3"
    >
      {{ loadError }}
    </div>

    <div
      v-else-if="slides.length === 0"
      class="text-sm text-gray-500 bg-violet-50/50 border border-violet-100 rounded-2xl p-6 text-center"
    >
      <FileText class="w-8 h-8 text-violet-400 mx-auto mb-2" />
      Слайдов нет. Сначала загрузите презентацию и запустите анализ.
    </div>

    <template v-else-if="current">
      <div
        class="bg-white rounded-2xl border border-gray-100 overflow-hidden shadow-soft"
      >
        <!-- top bar -->
        <div class="px-5 py-3 border-b border-gray-100 flex items-center justify-between gap-3">
          <button
            type="button"
            class="text-sm text-violet-700 hover:text-violet-600 font-medium transition"
            @click="emit('back')"
          >
            ← Назад
          </button>

          <div class="text-sm text-gray-500">
            Слайд
            <span class="font-semibold text-gray-900">{{ current.slide_number }}</span>
            из {{ slides.length }}
          </div>

          <div class="flex gap-1">
            <button
              class="w-8 h-8 grid place-items-center rounded-lg hover:bg-gray-100 disabled:opacity-30 transition"
              :disabled="currentIdx === 0"
              aria-label="Предыдущий"
              @click="prev"
            >
              <ChevronLeft class="w-4 h-4" />
            </button>
            <button
              class="w-8 h-8 grid place-items-center rounded-lg hover:bg-gray-100 disabled:opacity-30 transition"
              :disabled="currentIdx === slides.length - 1"
              aria-label="Следующий"
              @click="next"
            >
              <ChevronRight class="w-4 h-4" />
            </button>
          </div>
        </div>

        <!-- two-panel: slide preview + editor -->
        <div class="grid grid-cols-1 md:grid-cols-5 gap-5 p-5">
          <div class="md:col-span-2">
            <div class="aspect-[4/3] rounded-xl overflow-hidden bg-gray-50 border border-gray-200 shadow-sm grid place-items-center">
              <img
                v-if="current.image_url"
                :src="current.image_url"
                :alt="`Слайд ${current.slide_number}`"
                class="w-full h-full object-contain bg-white"
              />
              <span v-else class="text-xs text-gray-400">Изображение недоступно</span>
            </div>
          </div>

          <div class="md:col-span-3 flex flex-col">
            <label class="block text-sm font-medium text-gray-700 mb-2">Текст озвучки</label>
            <textarea
              v-model="buffer"
              placeholder="Введите текст, который будет озвучен на этом слайде…"
              class="flex-1 min-h-[260px] resize-none px-4 py-3 text-sm leading-relaxed bg-white
                     border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400 transition"
              @input="scheduleSave(); canRevert = false"
              @blur="persistCurrent"
            />
            <div class="flex justify-between text-xs text-gray-500 mt-2">
              <span>
                Слов: <span class="font-medium text-gray-700">{{ wordCount }}</span>
                <span class="text-gray-300 mx-1.5">·</span>
                ≈ {{ estDurationLabel }}
              </span>
              <span v-if="isSavingCurrent" class="text-violet-700">сохранение…</span>
            </div>
          </div>
        </div>

        <!-- thumbnail strip -->
        <div class="px-5 pb-3 overflow-x-auto">
          <div class="flex gap-2">
            <button
              v-for="(s, idx) in slides"
              :key="s.id"
              type="button"
              :class="[
                'shrink-0 relative rounded-md overflow-hidden border-2 transition',
                idx === currentIdx
                  ? 'border-violet-600 ring-2 ring-violet-200'
                  : 'border-transparent hover:border-violet-300 opacity-70 hover:opacity-100',
              ]"
              :style="{ width: '64px', height: '48px' }"
              @click="goTo(idx)"
            >
              <img
                v-if="s.image_url"
                :src="s.image_url"
                :alt="`Слайд ${idx + 1}`"
                class="w-full h-full object-cover"
              />
              <div
                v-else
                class="w-full h-full grid place-items-center text-[10px] font-medium bg-gray-100 text-gray-500"
              >
                {{ idx + 1 }}
              </div>
              <span
                v-if="(s.edited_text ?? s.generated_text ?? '').trim()"
                class="absolute bottom-0.5 right-0.5 w-1.5 h-1.5 rounded-full bg-violet-500"
              ></span>
            </button>
          </div>
        </div>

        <!-- sticky bottom -->
        <div class="border-t border-gray-100 bg-white">
          <div class="px-5 pt-3">
            <ProgressBar
              :value="editedCount"
              :total="slides.length"
              label="Прогресс редактирования"
            />
          </div>
          <div
            v-if="regenError"
            class="mx-5 mt-3 flex items-center justify-between gap-3 text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-xl px-3 py-2"
          >
            <span>{{ regenError }}</span>
            <NuxtLink
              to="/billing"
              class="shrink-0 text-xs font-medium text-violet-700 hover:text-violet-800 whitespace-nowrap"
            >
              Пополнить →
            </NuxtLink>
          </div>
          <div class="px-5 py-3 flex flex-wrap gap-2 justify-between items-center">
            <div class="flex gap-2 items-center">
              <UiButton
                variant="secondary"
                size="sm"
                :loading="!!isRegenCurrent"
                :disabled="!current.image_url"
                @click="guardedRegenerate"
              >
                <template #icon><Sparkles class="w-4 h-4" /></template>
                Регенерировать LLM
              </UiButton>
              <UiButton
                v-if="isRegenCurrent"
                variant="ghost"
                size="sm"
                @click="cancelRegen"
              >
                Отмена
              </UiButton>
              <UiButton
                v-if="canRevert && !isRegenCurrent"
                variant="ghost"
                size="sm"
                @click="revertText"
              >
                <template #icon><RotateCcw class="w-4 h-4" /></template>
                Откатить
              </UiButton>
            </div>

            <div class="flex flex-wrap gap-2">
              <UiButton
                variant="secondary"
                size="sm"
                :loading="!!isSavingCurrent"
                @click="persistCurrent"
              >
                <template #icon><Save class="w-4 h-4" /></template>
                Сохранить
              </UiButton>
              <UiButton
                variant="primary"
                size="md"
                :disabled="slides.length === 0"
                @click="async () => { await persistCurrent(); emit('ready') }"
              >
                Генерировать видео →
              </UiButton>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
