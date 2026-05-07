<script setup lang="ts">
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

const slides = ref<SlideText[]>([])
const loading = ref(true)
const loadError = ref('')
const currentIdx = ref(0)
const buffer = ref('')
const savingIds = ref<Set<string>>(new Set())
const regenIds = ref<Set<string>>(new Set())
let saveTimer: ReturnType<typeof setTimeout> | null = null

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
  slides.value.filter(s => (s.edited_text ?? '').trim().length > 0 || (s.generated_text ?? '').trim().length > 0).length,
)

const progressPct = computed(() =>
  slides.value.length > 0 ? Math.round((editedCount.value / slides.value.length) * 100) : 0,
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

const regenerate = async () => {
  const slide = current.value
  if (!slide) return
  regenIds.value.add(slide.id)
  try {
    const updated = await apiFetch<SlideText>(
      `/lessons/${props.lessonId}/slides/${slide.id}/regenerate`,
      { method: 'POST' },
    )
    const idx = slides.value.findIndex(s => s.id === slide.id)
    if (idx >= 0) slides.value[idx] = updated
    if (slide.id === current.value?.id) {
      buffer.value = updated.edited_text ?? updated.generated_text ?? ''
    }
  } finally {
    regenIds.value.delete(slide.id)
  }
}

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

onMounted(() => {
  loadSlides()
  window.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  if (saveTimer) clearTimeout(saveTimer)
})

defineExpose({ persistCurrent })
</script>

<template>
  <div class="space-y-4">
    <div v-if="loading" class="text-sm text-gray-500">Загрузка слайдов…</div>
    <div v-else-if="loadError" class="text-sm text-red-600 bg-red-50 border border-red-200 rounded p-3">
      {{ loadError }}
    </div>
    <div v-else-if="slides.length === 0" class="text-sm text-gray-500 bg-gray-50 rounded p-4">
      Слайдов нет. Сначала загрузите презентацию и запустите анализ.
    </div>

    <template v-else-if="current">
      <!-- Top bar -->
      <div class="flex items-center justify-between gap-3 border-b border-gray-200 pb-3">
        <button
          type="button"
          class="text-sm text-brand hover:underline"
          @click="$emit('back')"
        >
          ← Назад
        </button>
        <div class="text-sm font-medium text-gray-700">
          Слайд {{ current.slide_number }} из {{ slides.length }}
        </div>
        <div class="flex gap-2">
          <button
            type="button"
            class="px-3 py-1.5 border rounded-lg text-sm hover:bg-gray-50 disabled:opacity-40"
            :disabled="currentIdx === 0"
            @click="prev"
          >
            ← Пред
          </button>
          <button
            type="button"
            class="px-3 py-1.5 border rounded-lg text-sm hover:bg-gray-50 disabled:opacity-40"
            :disabled="currentIdx === slides.length - 1"
            @click="next"
          >
            След →
          </button>
        </div>
      </div>

      <!-- Split view -->
      <div class="grid grid-cols-1 lg:grid-cols-[2fr_3fr] gap-5">
        <!-- Slide preview -->
        <div class="bg-gray-50 border rounded-xl p-3 flex items-center justify-center min-h-[260px]">
          <img
            v-if="current.image_url"
            :src="current.image_url"
            :alt="`Слайд ${current.slide_number}`"
            class="max-w-full max-h-[60vh] object-contain rounded shadow-sm bg-white"
          />
          <span v-else class="text-sm text-gray-400">Изображение недоступно</span>
        </div>

        <!-- Text editor -->
        <div class="flex flex-col">
          <label class="block text-sm font-medium text-gray-700 mb-1">Текст озвучки</label>
          <textarea
            v-model="buffer"
            class="w-full flex-1 min-h-[400px] max-h-[70vh] resize-y border rounded-lg px-4 py-3 text-base leading-relaxed focus:outline-none focus:ring-2 focus:ring-brand/40"
            placeholder="Введите текст, который будет озвучен на этом слайде…"
            @input="scheduleSave"
            @blur="persistCurrent"
          />

          <div class="flex flex-wrap items-center justify-between gap-3 mt-3">
            <div class="text-xs text-gray-500">
              Слов: <span class="font-medium text-gray-700">{{ wordCount }}</span>
              <span class="text-gray-300 mx-1.5">·</span>
              ≈ {{ estDurationLabel }}
              <span v-if="isSavingCurrent" class="ml-3 text-brand">сохранение…</span>
            </div>
            <div class="flex flex-wrap gap-2">
              <button
                type="button"
                class="px-3 py-1.5 border rounded-lg text-sm hover:bg-gray-50 disabled:opacity-50"
                :disabled="isRegenCurrent || !current.image_url"
                @click="regenerate"
              >
                {{ isRegenCurrent ? 'Регенерация…' : 'Регенерировать LLM' }}
              </button>
              <button
                type="button"
                class="px-3 py-1.5 bg-brand text-white rounded-lg text-sm disabled:opacity-50"
                :disabled="isSavingCurrent"
                @click="persistCurrent"
              >
                Сохранить
              </button>
              <button
                type="button"
                class="px-3 py-1.5 border rounded-lg text-sm text-gray-400 cursor-not-allowed"
                disabled
                title="Скоро"
              >
                Расширенный редактор
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Bottom bar with progress -->
      <div class="border-t border-gray-200 pt-3 mt-2 space-y-3">
        <div class="flex items-center gap-3 text-sm">
          <span class="text-gray-500 whitespace-nowrap">Прогресс: {{ editedCount }}/{{ slides.length }}</span>
          <div class="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
            <div
              class="h-full bg-brand transition-all"
              :style="{ width: `${progressPct}%` }"
            />
          </div>
          <span class="text-gray-500 tabular-nums w-10 text-right">{{ progressPct }}%</span>
        </div>

        <div class="flex flex-wrap items-center justify-between gap-3">
          <div class="flex flex-wrap gap-1.5">
            <button
              v-for="(s, idx) in slides"
              :key="s.id"
              type="button"
              :class="[
                'w-7 h-7 text-xs rounded font-medium border transition',
                idx === currentIdx
                  ? 'bg-brand text-white border-brand'
                  : (s.edited_text ?? s.generated_text ?? '').trim()
                    ? 'bg-brand/10 text-brand border-brand/30 hover:bg-brand/20'
                    : 'bg-white text-gray-400 border-gray-200 hover:bg-gray-50',
              ]"
              @click="goTo(idx)"
            >
              {{ idx + 1 }}
            </button>
          </div>

          <button
            type="button"
            class="px-5 py-2 bg-brand text-white rounded-lg font-medium disabled:opacity-50"
            :disabled="slides.length === 0"
            @click="async () => { await persistCurrent(); emit('ready') }"
          >
            Генерировать видео →
          </button>
        </div>
      </div>
    </template>
  </div>
</template>
