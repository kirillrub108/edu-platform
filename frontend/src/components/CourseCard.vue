<script setup lang="ts">
import { BookOpen, ArrowRight, Archive, RotateCcw } from 'lucide-vue-next'
import StatusBadge from './StatusBadge.vue'

const props = withDefaults(
  defineProps<{
    course: {
      id: string
      title: string
      description?: string | null
      cover_url?: string | null
      is_published: boolean
      is_archived?: boolean
      days_until_purge?: number | null
      lessons_count?: number
      gradient_idx?: number
    }
    to?: string
    // Render the "В архив" / "Восстановить" action buttons + emit events.
    // Off by default so other CourseCard usages (e.g. /courses) stay read-only.
    showActions?: boolean
  }>(),
  { showActions: false },
)

const emit = defineEmits<{
  (e: 'archive', id: string): void
  (e: 'restore', id: string): void
}>()

const archived = computed(() => props.course.is_archived === true)

const gradients = [
  'from-violet-500 via-purple-500 to-fuchsia-500',
  'from-indigo-500 via-violet-500 to-purple-500',
  'from-purple-500 via-fuchsia-500 to-violet-500',
  'from-violet-600 via-indigo-500 to-purple-500',
]
const gradient = computed(() => gradients[(props.course.gradient_idx ?? 0) % gradients.length])

const lessonsCount = computed(() => props.course.lessons_count ?? 0)
const lessonsLabel = computed(() => {
  const n = lessonsCount.value
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return 'урок'
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 'урока'
  return 'уроков'
})

const purgeLabel = computed(() => {
  const d = props.course.days_until_purge
  if (d == null) return 'в архиве'
  if (d <= 0) return 'удалится сегодня'
  const mod10 = d % 10
  const mod100 = d % 100
  let unit = 'дней'
  if (mod10 === 1 && mod100 !== 11) unit = 'день'
  else if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) unit = 'дня'
  return `удалится через ${d} ${unit}`
})

const onArchive = () => {
  if (
    typeof window !== 'undefined'
    && !window.confirm(
      'Отправить курс в архив? Студенты потеряют доступ, а через 30 дней он будет '
      + 'удалён безвозвратно. Восстановить можно в любой момент до удаления.',
    )
  ) return
  emit('archive', props.course.id)
}

const onRestore = () => emit('restore', props.course.id)
</script>

<template>
  <div
    class="group relative bg-white rounded-2xl overflow-hidden border border-gray-100 shadow-soft transition-all duration-150"
    :class="archived
      ? 'opacity-75 hover:opacity-100'
      : 'hover:scale-[1.01] hover:border-violet-200 hover:shadow-soft-hover'"
  >
    <!-- Stretched navigation link: covers the whole card so the card is clickable
         without nesting the action buttons inside an <a>. Buttons sit above it. -->
    <NuxtLink
      :to="to ?? `/courses/${course.id}`"
      class="absolute inset-0 z-10"
      :aria-label="course.title"
    />

    <div class="relative h-32 overflow-hidden">
      <img
        v-if="course.cover_url"
        :src="course.cover_url"
        :alt="course.title"
        class="w-full h-full object-cover"
        :class="archived ? 'grayscale' : ''"
      />
      <div v-else :class="['h-full bg-gradient-to-br', gradient, archived ? 'grayscale' : '']" />

      <!-- Archive badge -->
      <span
        v-if="archived"
        class="absolute top-2 left-2 z-20 inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-gray-900/70 text-white backdrop-blur"
      >
        <Archive class="w-3 h-3" /> Архив
      </span>

      <!-- Action buttons (above the stretched link) -->
      <div v-if="showActions" class="absolute top-2 right-2 z-20">
        <button
          v-if="!archived"
          type="button"
          class="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium bg-white/90 text-gray-700 shadow-sm backdrop-blur transition hover:bg-white hover:text-rose-600"
          @click.stop.prevent="onArchive"
        >
          <Archive class="w-3.5 h-3.5" /> В архив
        </button>
        <button
          v-else
          type="button"
          class="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium bg-violet-600 text-white shadow-sm transition hover:bg-violet-700"
          @click.stop.prevent="onRestore"
        >
          <RotateCcw class="w-3.5 h-3.5" /> Восстановить
        </button>
      </div>
    </div>

    <div class="p-5">
      <h3 class="font-semibold text-gray-900 text-lg leading-tight">{{ course.title }}</h3>
      <p v-if="course.description" class="text-sm text-gray-500 mt-1.5 line-clamp-2">
        {{ course.description }}
      </p>
      <div class="flex items-center justify-between mt-4">
        <div class="flex items-center gap-1.5 text-xs text-gray-500">
          <BookOpen class="w-3.5 h-3.5" />
          {{ lessonsCount }} {{ lessonsLabel }}
        </div>
        <StatusBadge :status="course.is_published ? 'published' : 'draft'" />
      </div>
      <div class="mt-4 pt-4 border-t border-gray-100 flex items-center justify-between text-sm">
        <template v-if="archived">
          <span class="inline-flex items-center gap-1.5 text-gray-500">
            <Archive class="w-3.5 h-3.5" />
            {{ purgeLabel }}
          </span>
        </template>
        <template v-else>
          <span class="text-violet-700 font-medium group-hover:text-violet-600">Открыть</span>
          <ArrowRight class="w-4 h-4 text-violet-700 transform transition group-hover:translate-x-0.5" />
        </template>
      </div>
    </div>
  </div>
</template>
